/** TaskFormDialog 白盒表单渲染测试。
 *
 * 聚焦组件渲染：切到白盒后展示源码配置/Maven 字段，formErrors 透传到字段错误。
 * 校验逻辑位于 useTasks，此处只验证渲染路径。
 */

import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";

import TaskFormDialog from "../TaskFormDialog.vue";
import type { Project, ModelConfig } from "../../../types";
import type { TaskFormState } from "../../../composables/useTasks";
import { emptyPromptExtensions } from "../../../promptExtensions";
import { SENTINEL_DEFAULT } from "../../../utils";

const projects: Project[] = [{ projectId: "p1", name: "测试项目" } as Project];
const enabledModels: ModelConfig[] = [];

function makeForm(taskType: "blackbox" | "whitebox" = "blackbox"): TaskFormState {
  return {
    editingId: null,
    goal: "分析登录",
    name: "",
    projectId: "p1",
    modelConfigId: SENTINEL_DEFAULT,
    taskType,
    blackbox: {
      startUrl: "https://example.com",
      maxSteps: null,
      timeoutSeconds: null,
      captureScreenshots: SENTINEL_DEFAULT,
      parameters: [],
      promptExtensions: emptyPromptExtensions(),
    },
    whitebox: {
      sourceType: "git",
      repoUrl: "https://git.example.com/proj.git",
      sourcePath: "",
      ref: "",
      scope: "all",
      targetModules: [],
      mavenClasspathMode: "AUTO",
      mavenOffline: false,
      mavenAutoDetect: true,
      mavenGenerateClasspath: true,
      mavenClasspathFile: "",
      mavenExecutable: "",
      mavenSettingsXml: "",
      mavenLocalRepository: "",
      mavenOfflineTimeoutSeconds: null,
      mavenOnlineTimeoutSeconds: null,
      mavenPrepareReactorArtifacts: false,
    },
  };
}

function mountForm(form: TaskFormState, formErrors: Record<string, string> = {}) {
  return mount(TaskFormDialog, {
    props: {
      visible: true,
      form,
      editing: false,
      formErrors,
      projects,
      enabledModels,
    },
    global: {
      stubs: {
        // el-dialog 默认 append-to-body，内容被 teleport 到 body，
        // 测试中 stub 为内联渲染（含 footer 槽）以便断言
        ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
      },
    },
  });
}

describe("TaskFormDialog", () => {
  it("默认黑盒态不渲染白盒字段", () => {
    const wrapper = mountForm(makeForm("blackbox"));
    expect(wrapper.text()).toContain("黑盒测试");
    expect(wrapper.text()).not.toContain("源码来源");
  });

  it("切到白盒后渲染源码配置与 Maven 字段", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form: makeForm("whitebox") });
    const text = wrapper.text();
    expect(text).toContain("白盒分析");
    expect(text).toContain("源码来源");
    expect(text).toContain("仓库 URL");
    expect(text).toContain("分析范围");
    expect(text).toContain("Classpath 模式");
  });

  it("scope=modules 时渲染目标模块输入", async () => {
    const form = makeForm("whitebox");
    form.whitebox.scope = "modules";
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form });
    expect(wrapper.text()).toContain("目标模块");
  });

  it("白盒 git 来源时渲染仓库 URL 输入框", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form: makeForm("whitebox") });
    expect(wrapper.find('input[placeholder*="github.com"]').exists()).toBe(true);
  });

  it("白盒 local 来源时渲染服务端路径输入框", async () => {
    const form = makeForm("whitebox");
    form.whitebox.sourceType = "local";
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form });
    expect(wrapper.find('input[placeholder*="/opt"]').exists()).toBe(true);
  });

  it("白盒下目标输入框置灰禁用", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form: makeForm("whitebox") });
    expect(wrapper.find("textarea").attributes("disabled")).toBeDefined();
  });

  it("白盒下模型配置下拉置灰禁用", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    await wrapper.setProps({ form: makeForm("whitebox") });
    // Element Plus select 的 disabled 态渲染在 .el-select__wrapper 的 is-disabled class
    const disabledWrappers = wrapper.findAll(".el-select__wrapper.is-disabled");
    expect(disabledWrappers.length).toBeGreaterThan(0);
  });

  it("切到白盒且 goal 为空时自动填充固定文案", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    const whitebox = makeForm("whitebox");
    whitebox.goal = "";
    await wrapper.setProps({ form: whitebox });
    expect(wrapper.find("textarea").element.value).toBe("白盒静态分析");
  });

  it("由自动填充产生的白盒默认文案在切回黑盒时清空", async () => {
    const wrapper = mountForm(makeForm("blackbox"));
    const whitebox = makeForm("whitebox");
    whitebox.goal = "";
    await wrapper.setProps({ form: whitebox });
    expect(wrapper.find("textarea").element.value).toBe("白盒静态分析");

    const blackbox = makeForm("blackbox");
    blackbox.goal = "";
    await wrapper.setProps({ form: blackbox });
    expect(wrapper.find("textarea").element.value).toBe("");
  });

  it("formErrors.repoUrl 透传到字段错误展示", async () => {
    // el-form-item 的错误态经 100ms refDebounced 后才显示
    vi.useFakeTimers();
    const wrapper = mountForm(makeForm("blackbox"), { repoUrl: "Git 仓库地址不能为空" });
    await wrapper.setProps({ form: makeForm("whitebox") });
    vi.advanceTimersByTime(150);
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("Git 仓库地址不能为空");
    vi.useRealTimers();
  });

  it("editing 时保存按钮文案为保存", () => {
    const wrapper = mount(TaskFormDialog, {
      props: {
        visible: true,
        form: makeForm(),
        editing: true,
        formErrors: {},
        projects,
        enabledModels,
      },
      global: {
        stubs: {
          ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
        },
      },
    });
    expect(wrapper.text()).toContain("保存");
  });
});
