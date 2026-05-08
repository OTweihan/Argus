import { reactive, ref, type Ref } from "vue";
import { ElMessageBox } from "element-plus";
import { api, type ProjectPayload } from "../api";
import type { Project } from "../types";
import { errorMessage, nullableText, parseJsonObject, upsertById } from "../utils";

interface ProjectForm {
  editingId: string | null;
  name: string;
  description: string;
  baseUrl: string;
  gitUrl: string;
  authStateName: string;
  defaultMaxSteps: number | null;
  defaultTimeoutSeconds: number | null;
  defaultCaptureScreenshots: boolean;
  parameters: string;
}

export function useProjects(opts: {
  projects: Ref<Project[]>;
  error: Ref<string>;
  message: Ref<string>;
  formErrors: Record<string, string>;
}) {
  const { projects, error, message, formErrors } = opts;
  const projectForm = reactive<ProjectForm>(defaultProjectForm());
  const showProjectDialog = ref(false);

  async function loadProjects(): Promise<void> {
    const res = await api.listProjects();
    projects.value = res.projects;
  }

  async function saveProject(): Promise<void> {
    clearFormErrors();
    if (!String(projectForm.name).trim()) {
      formErrors.name = "名称不能为空";
      return;
    }
    const baseUrl = nullableText(projectForm.baseUrl);
    if (baseUrl && !/^https?:\/\/.+/.test(baseUrl)) {
      formErrors.baseUrl = "请输入合法的 http/https URL";
      return;
    }
    let parameters: Record<string, unknown>;
    try {
      parameters = parseJsonObject(projectForm.parameters, "参数 JSON");
    } catch {
      formErrors.projectParameters = "必须为合法 JSON";
      return;
    }
    try {
      const payload: ProjectPayload = {
        name: String(projectForm.name).trim(),
        description: nullableText(projectForm.description),
        baseUrl,
        gitUrl: nullableText(projectForm.gitUrl),
        authStateName: nullableText(projectForm.authStateName),
        defaultMaxSteps: projectForm.defaultMaxSteps,
        defaultTimeoutSeconds: projectForm.defaultTimeoutSeconds,
        defaultCaptureScreenshots: projectForm.defaultCaptureScreenshots,
        parameters,
      };
      const project = projectForm.editingId
        ? await api.updateProject(projectForm.editingId, payload)
        : await api.createProject(payload);
      const wasEditing = Boolean(projectForm.editingId);
      projects.value = upsertById(projects.value, project, "projectId");
      showProjectDialog.value = false;
      resetProjectForm();
      message.value = wasEditing ? "项目已更新。" : "项目已创建。";
      error.value = "";
    } catch (caught) {
      error.value = errorMessage(caught);
      message.value = "";
    }
  }

  function editProject(project: Project): void {
    Object.assign(projectForm, {
      editingId: project.projectId,
      name: project.name ?? "",
      description: project.description ?? "",
      baseUrl: project.baseUrl ?? "",
      gitUrl: project.gitUrl ?? "",
      authStateName: project.authStateName ?? "",
      defaultMaxSteps: project.defaultMaxSteps ?? null,
      defaultTimeoutSeconds: project.defaultTimeoutSeconds ?? null,
      defaultCaptureScreenshots: project.defaultCaptureScreenshots,
      parameters: JSON.stringify(project.parameters, null, 2),
    });
    error.value = "";
    clearFormErrors();
    showProjectDialog.value = true;
  }

  async function deleteProject(projectId: string): Promise<void> {
    try {
      await ElMessageBox.confirm("确认删除这个项目？", "警告", {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
      });
      await api.deleteProject(projectId);
      await loadProjects();
    } catch (caught) {
      if (caught === "cancel") return;
      error.value = errorMessage(caught);
    }
  }

  function openNewProjectDialog(): void {
    resetProjectForm();
    error.value = "";
    clearFormErrors();
    showProjectDialog.value = true;
  }

  function resetProjectForm(): void {
    Object.assign(projectForm, defaultProjectForm());
  }

  function clearFormErrors(): void {
    for (const key of Object.keys(formErrors)) {
      delete formErrors[key];
    }
  }

  return {
    projectForm,
    showProjectDialog,
    loadProjects,
    saveProject,
    editProject,
    deleteProject,
    openNewProjectDialog,
    resetProjectForm,
  };
}

function defaultProjectForm(): ProjectForm {
  return {
    editingId: null,
    name: "",
    description: "",
    baseUrl: "",
    gitUrl: "",
    authStateName: "",
    defaultMaxSteps: null,
    defaultTimeoutSeconds: null,
    defaultCaptureScreenshots: true,
    parameters: "{}",
  };
}
