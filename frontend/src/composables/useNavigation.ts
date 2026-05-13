import { onMounted, onUnmounted, ref } from "vue";

export type ViewKey = "dashboard" | "projects" | "tasks" | "models" | "task-detail";

export function useNavigation() {
    const view = ref<ViewKey>("dashboard");
    const initialDetailTaskId = ref<string | null>(null);

    function parseHash(hash: string): { view: ViewKey; taskId: string | null } {
        const cleaned = hash.replace(/^#/, "");
        const parts = cleaned.split("/");
        const viewName = parts[0] as ViewKey;
        const validViews: ViewKey[] = ["dashboard", "projects", "tasks", "models", "task-detail"];
        if (validViews.includes(viewName)) {
            return { view: viewName, taskId: parts[1] || null };
        }
        return { view: "dashboard", taskId: null };
    }

    function changeView(nextView: ViewKey): void {
        view.value = nextView;
        window.location.hash = nextView;
    }

    function onHashChange(): void {
        const { view: parsedView } = parseHash(window.location.hash);
        view.value = parsedView;
    }

    onMounted(() => {
        const { view: parsedView, taskId } = parseHash(window.location.hash);
        view.value = parsedView;
        if (parsedView === "task-detail" && taskId) {
            initialDetailTaskId.value = taskId;
        }
        window.addEventListener("hashchange", onHashChange);
    });

    onUnmounted(() => {
        window.removeEventListener("hashchange", onHashChange);
    });

    return { view, changeView, initialDetailTaskId };
}
