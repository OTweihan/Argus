/** useTasks 白盒表单专项测试：payload 构造与编辑回填。
 *
 * useTasks 的内部 helper 未导出，通过挂载 harness 组件暴露 taskForm/saveTask/
 * openEditTaskDialog，间接断言 buildWhiteboxPayload 与 _restoreWhiteboxForm。
 */

import { computed, defineComponent, reactive, ref } from "vue";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import type { Project, Task } from "../../types";

vi.mock("../../api", () => ({
    createTask: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
    restartTask: vi.fn(),
    startTask: vi.fn(),
    inferTaskLimits: vi.fn(),
}));

vi.mock("../useTaskList", () => ({
    useTaskList: () => ({
        loadTasks: vi.fn(),
        total: ref(0),
        page: ref(1),
    }),
}));

vi.mock("../useTaskSelection", () => ({
    useTaskSelection: () => ({
        selectedTaskId: ref<string | null>(null),
        selectedTask: computed(() => null),
    }),
}));

import * as api from "../../api";
import { useTasks } from "../useTasks";

const apiCreateTaskMock = api.createTask as unknown as ReturnType<typeof vi.fn>;

const Harness = defineComponent({
    setup() {
        const allTasks = ref<Task[]>([]);
        const projects = ref<Project[]>([{ projectId: "p1", name: "测试项目" } as Project]);
        const models = ref([]);
        const error = ref("");
        const message = ref("");
        const formErrors = reactive<Record<string, string>>({});
        const view = ref("tasks");
        const t = useTasks({
            allTasks,
            projects,
            models,
            error,
            message,
            formErrors,
            view,
        });
        return { t };
    },
    template: "<div />",
});

function mountHarness() {
    const wrapper = mount(Harness);
    return wrapper.vm.t as ReturnType<typeof useTasks>;
}

describe("useTasks 白盒 payload", () => {
    beforeEach(() => {
        apiCreateTaskMock.mockReset();
    });

    it("saveTask 构造白盒 payload：git 来源 + scope=modules 过滤 targetModules", async () => {
        const t = mountHarness();
        t.taskForm.goal = "分析登录";
        t.taskForm.taskType = "whitebox";
        t.taskForm.whitebox.sourceType = "git";
        t.taskForm.whitebox.repoUrl = "https://git.example.com/repo.git";
        t.taskForm.whitebox.ref = "main";
        t.taskForm.whitebox.scope = "modules";
        t.taskForm.whitebox.targetModules = ["module-a", "", "module-b"];
        apiCreateTaskMock.mockResolvedValue({ taskId: "t-new" });

        await t.saveTask();
        await flushPromises();

        expect(apiCreateTaskMock).toHaveBeenCalledTimes(1);
        const payload = apiCreateTaskMock.mock.calls[0][0];
        expect(payload.taskType).toBe("whitebox");
        expect(payload.whiteboxConfig.sourceType).toBe("git");
        expect(payload.whiteboxConfig.repoUrl).toBe("https://git.example.com/repo.git");
        expect(payload.whiteboxConfig.ref).toBe("main");
        expect(payload.whiteboxConfig.scope).toBe("modules");
        // scope != all 时保留过滤后的 targetModules
        expect(payload.whiteboxConfig.targetModules).toEqual(["module-a", "module-b"]);
        // 白盒不携带黑盒字段
        expect(payload.startUrl).toBeNull();
        expect(payload.captureScreenshots).toBeNull();
    });

    it("scope=all 时 targetModules 置空", async () => {
        const t = mountHarness();
        t.taskForm.goal = "分析登录";
        t.taskForm.taskType = "whitebox";
        t.taskForm.whitebox.sourceType = "local";
        t.taskForm.whitebox.sourcePath = "/opt/ws/proj";
        t.taskForm.whitebox.scope = "all";
        t.taskForm.whitebox.targetModules = ["module-a"];
        apiCreateTaskMock.mockResolvedValue({ taskId: "t-new" });

        await t.saveTask();
        await flushPromises();

        const payload = apiCreateTaskMock.mock.calls[0][0];
        expect(payload.whiteboxConfig.scope).toBe("all");
        expect(payload.whiteboxConfig.targetModules).toEqual([]);
        expect(payload.whiteboxConfig.sourcePath).toBe("/opt/ws/proj");
    });

    it("openEditTaskDialog 从 whiteboxConfigView 回填表单", () => {
        const t = mountHarness();
        const task = {
            taskId: "t-edit",
            goal: "分析",
            name: null,
            projectId: "p1",
            taskType: "whitebox",
            startUrl: null,
            parameters: {},
            whiteboxConfigView: {
                status: "VALID",
                config: {
                    sourceType: "git",
                    repoUrl: "https://git.example.com/repo.git",
                    sourcePath: null,
                    ref: "release/1.0",
                    scope: "endpoints",
                    targetModules: ["mod-a"],
                    maven: {
                        classpathMode: "CACHE_ONLY",
                        offline: true,
                        autoDetect: false,
                        generateClasspath: true,
                    },
                },
            },
        } as unknown as Task;

        t.openEditTaskDialog(task);

        expect(t.taskForm.taskType).toBe("whitebox");
        expect(t.taskForm.editingId).toBe("t-edit");
        expect(t.taskForm.whitebox.sourceType).toBe("git");
        expect(t.taskForm.whitebox.repoUrl).toBe("https://git.example.com/repo.git");
        expect(t.taskForm.whitebox.ref).toBe("release/1.0");
        expect(t.taskForm.whitebox.scope).toBe("endpoints");
        expect(t.taskForm.whitebox.targetModules).toEqual(["mod-a"]);
        expect(t.taskForm.whitebox.mavenClasspathMode).toBe("CACHE_ONLY");
        expect(t.taskForm.whitebox.mavenOffline).toBe(true);
        expect(t.taskForm.whitebox.mavenAutoDetect).toBe(false);
    });

    it("openEditTaskDialog 编辑保存走 updateTask 且保留白盒配置", async () => {
        const t = mountHarness();
        const task = {
            taskId: "t-edit",
            goal: "分析",
            name: null,
            projectId: "p1",
            taskType: "whitebox",
            startUrl: null,
            parameters: {},
            whiteboxConfigView: {
                status: "VALID",
                config: {
                    sourceType: "local",
                    repoUrl: null,
                    sourcePath: "/opt/ws/proj",
                    ref: null,
                    scope: "all",
                    targetModules: [],
                    maven: null,
                },
            },
        } as unknown as Task;
        const apiUpdateTaskMock = api.updateTask as unknown as ReturnType<typeof vi.fn>;
        apiUpdateTaskMock.mockResolvedValue({ taskId: "t-edit" });

        t.openEditTaskDialog(task);
        await t.saveTask();
        await flushPromises();

        expect(apiUpdateTaskMock).toHaveBeenCalledTimes(1);
        const [taskId, payload] = apiUpdateTaskMock.mock.calls[0];
        expect(taskId).toBe("t-edit");
        expect(payload.taskType).toBe("whitebox");
        expect(payload.whiteboxConfig.sourceType).toBe("local");
        expect(payload.whiteboxConfig.sourcePath).toBe("/opt/ws/proj");
    });
});
