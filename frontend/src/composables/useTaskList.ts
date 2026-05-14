import { ref, watch, type Ref } from "vue";
import { listTasks as apiListTasks } from "../api";
import type { Task } from "../types";
import { useDebounceFn } from "./useDebounceFn";

export function useTaskList(opts: {
    allTasks: Ref<Task[]>;
}) {
    const { allTasks } = opts;
    const taskStatusFilter = ref<TaskDisplayStatus | "">("");
    const taskProjectFilter = ref("");
    const taskSearchQuery = ref("");
    const page = ref(1);
    const pageSize = ref(20);
    const total = ref(0);
    const taskLoading = ref(false);

    async function loadTasks(): Promise<void> {
        taskLoading.value = true;
        try {
            const status = taskStatusFilter.value || undefined;
            const res = await apiListTasks({
                status,
                projectId: taskProjectFilter.value || undefined,
                q: taskSearchQuery.value.trim() || undefined,
                offset: (page.value - 1) * pageSize.value,
                limit: pageSize.value,
            });
            allTasks.value = res.tasks;
            total.value = res.total;
        } finally {
            taskLoading.value = false;
        }
    }

    function onPageChange(newPage: number): void {
        page.value = newPage;
        loadTasks();
    }

    function onPageSizeChange(newSize: number): void {
        pageSize.value = newSize;
        page.value = 1;
        loadTasks();
    }

    const debouncedSearch = useDebounceFn(() => {
        page.value = 1;
        void loadTasks();
    }, 300);
    watch(taskSearchQuery, debouncedSearch);

    watch([taskStatusFilter, taskProjectFilter], () => {
        page.value = 1;
        loadTasks();
    });

    return {
        taskStatusFilter,
        taskProjectFilter,
        taskSearchQuery,
        page,
        pageSize,
        total,
        taskLoading,
        loadTasks,
        onPageChange,
        onPageSizeChange,
    };
}

type TaskDisplayStatus = "pending" | "queued" | "running" | "completed" | "failed" | "timeout" | "cancelled";
