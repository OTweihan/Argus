/** useTasks 白盒表单专项测试：payload 构造与编辑回填。
 *
 * useTasks 的内部 helper 未导出，通过挂载 harness 组件暴露 taskForm/saveTask/
 * openEditTaskDialog，间接断言 buildWhiteboxPayload 与 _restoreWhiteboxForm。
 */

import { computed, defineComponent, nextTick, reactive, ref } from "vue";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import type { Project, Task } from "../../types";

vi.mock("../../api", () => {
  class ApiError extends Error {
    constructor(
      message: string,
      public status: number,
      public code = "HTTP_ERROR",
      public details: Record<string, unknown> = {},
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    createTask: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
    restartTask: vi.fn(),
    startTask: vi.fn(),
    inferTaskLimits: vi.fn(),
  };
});

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

describe("useTasks autoFillLimits — 取消与乱序防护", () => {
  const apiInferTaskLimitsMock = api.inferTaskLimits as unknown as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    apiInferTaskLimitsMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  type Limits = { maxSteps: number; timeoutSeconds: number };

  /** 设定 goal 并推进 400ms 防抖，让 autoFillLimits 真正发出推断请求。 */
  async function fireInference(
    t: ReturnType<typeof useTasks>,
    goal: string,
  ): Promise<void> {
    t.taskForm.goal = goal;
    await nextTick(); // goal watch 先跑，防抖计时器就位
    await vi.advanceTimersByTimeAsync(400);
    await flushPromises();
  }

  it("正常推断写回 blackbox maxSteps/timeoutSeconds", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    apiInferTaskLimitsMock.mockResolvedValue({ maxSteps: 5, timeoutSeconds: 60 });

    await fireInference(t, "测试登录流程");

    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);
    expect(apiInferTaskLimitsMock.mock.calls[0][0]).toBe("测试登录流程");
    expect(apiInferTaskLimitsMock.mock.calls[0][1]).toBeUndefined();
    expect(t.taskForm.blackbox.maxSteps).toBe(5);
    expect(t.taskForm.blackbox.timeoutSeconds).toBe(60);
  });

  it("旧推断迟到返回不覆盖新推断结果（代次保护）", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolveFirst!: (v: Limits) => void;
    let resolveSecond!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolveFirst = res; }),
    );
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolveSecond = res; }),
    );

    // 第一次推断（goal="a"）挂起
    await fireInference(t, "a");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);

    // 修改 goal → 400ms 后第二次推断发出（取消第一次）
    await fireInference(t, "b");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(2);

    // 第二次先返回
    resolveSecond({ maxSteps: 8, timeoutSeconds: 90 });
    await flushPromises();
    expect(t.taskForm.blackbox.maxSteps).toBe(8);
    expect(t.taskForm.blackbox.timeoutSeconds).toBe(90);

    // 第一次迟到返回：代次已落后，应被丢弃
    resolveFirst({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();
    expect(t.taskForm.blackbox.maxSteps).toBe(8);
    expect(t.taskForm.blackbox.timeoutSeconds).toBe(90);
  });

  it("响应期间用户修改 goal：旧推断不覆盖用户输入", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolve!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolve = res; }),
    );

    await fireInference(t, "aaa");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);

    // 推断在途时用户继续编辑 goal（防抖窗口内尚未发出新推断）
    t.taskForm.goal = "bbb";
    resolve({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();

    // 目标已变，旧推断结果被丢弃
    expect(t.taskForm.blackbox.maxSteps).toBeNull();
    expect(t.taskForm.blackbox.timeoutSeconds).toBeNull();
  });

  it("响应期间切换 taskType：旧黑盒推断不写入", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolve!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolve = res; }),
    );

    await fireInference(t, "分析登录");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);

    t.taskForm.taskType = "whitebox";
    resolve({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();

    expect(t.taskForm.blackbox.maxSteps).toBeNull();
  });

  it("响应期间 startUrl 变化：旧黑盒推断不覆盖", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolve!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolve = res; }),
    );

    t.taskForm.goal = "分析登录";
    t.taskForm.blackbox.startUrl = "https://example.com";
    await nextTick();
    await vi.advanceTimersByTimeAsync(400);
    await flushPromises();
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);
    // 发起时 startUrl 快照
    expect(apiInferTaskLimitsMock.mock.calls[0][1]).toBe("https://example.com");

    t.taskForm.blackbox.startUrl = "https://other.example.com";
    resolve({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();

    expect(t.taskForm.blackbox.maxSteps).toBeNull();
  });

  it("推断在途时打开编辑对话框：旧推断不覆盖表单", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolve!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolve = res; }),
    );

    await fireInference(t, "分析登录");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);

    t.taskForm.editingId = "t-edit";
    resolve({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();

    expect(t.taskForm.blackbox.maxSteps).toBeNull();
  });

  it("目标被清空：取消在途推断并使其代次失效，不覆盖表单", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    let resolve!: (v: Limits) => void;
    apiInferTaskLimitsMock.mockImplementationOnce(
      () => new Promise<Limits>((res) => { resolve = res; }),
    );

    await fireInference(t, "aaa");
    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);
    expect(t.taskForm.blackbox.maxSteps).toBeNull();

    // 清空 goal：400ms 后 autoFillLimits 走 trimmed 空分支 → abort + 代次失效
    await fireInference(t, "");
    expect(t.taskForm.goal).toBe("");

    // 旧推断此时返回：代次已落后，应被丢弃
    resolve({ maxSteps: 5, timeoutSeconds: 60 });
    await flushPromises();
    expect(t.taskForm.blackbox.maxSteps).toBeNull();
    expect(t.taskForm.blackbox.timeoutSeconds).toBeNull();
  });

  it("推断失败：console.warn 且不写回；主动取消不告警", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const t = mountHarness();
    vi.useFakeTimers();

    // 第一次：真实失败 → warn
    apiInferTaskLimitsMock.mockRejectedValueOnce(new Error("网络错误"));
    await fireInference(t, "a");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(t.taskForm.blackbox.maxSteps).toBeNull();

    // 第二次：主动取消（client 转成 REQUEST_ABORTED）→ 不告警
    apiInferTaskLimitsMock.mockRejectedValueOnce(
      new api.ApiError("请求已取消。", 0, "REQUEST_ABORTED", { path: "/tasks/infer-limits" }),
    );
    await fireInference(t, "b");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(t.taskForm.blackbox.maxSteps).toBeNull();
  });

  it("白盒模式下推断结果不写回黑盒字段（行为保留）", async () => {
    const t = mountHarness();
    vi.useFakeTimers();
    t.taskForm.taskType = "whitebox";
    apiInferTaskLimitsMock.mockResolvedValue({ maxSteps: 5, timeoutSeconds: 60 });

    await fireInference(t, "分析登录");

    expect(apiInferTaskLimitsMock).toHaveBeenCalledTimes(1);
    expect(t.taskForm.blackbox.maxSteps).toBeNull();
    expect(t.taskForm.blackbox.timeoutSeconds).toBeNull();
  });
});
