import { reactive, ref, type Ref } from "vue";
import { api, type ProjectPayload } from "../api";
import type { Project } from "../types";
import { errorMessage, nullableNumber, nullableText, parseJsonObject, upsertById } from "../utils";

interface ProjectForm {
  editingId: string | null;
  name: string;
  description: string;
  baseUrl: string;
  gitUrl: string;
  authStateName: string;
  defaultMaxSteps: string;
  defaultTimeoutSeconds: string;
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
        baseUrl: nullableText(projectForm.baseUrl),
        gitUrl: nullableText(projectForm.gitUrl),
        authStateName: nullableText(projectForm.authStateName),
        defaultMaxSteps: nullableNumber(projectForm.defaultMaxSteps, "默认最大步骤"),
        defaultTimeoutSeconds: nullableNumber(projectForm.defaultTimeoutSeconds, "默认超时秒数"),
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
      defaultMaxSteps: project.defaultMaxSteps?.toString() ?? "",
      defaultTimeoutSeconds: project.defaultTimeoutSeconds?.toString() ?? "",
      defaultCaptureScreenshots: project.defaultCaptureScreenshots,
      parameters: JSON.stringify(project.parameters, null, 2),
    });
    error.value = "";
    clearFormErrors();
    showProjectDialog.value = true;
  }

  async function deleteProject(projectId: string): Promise<void> {
    if (!window.confirm("确认删除这个项目？")) return;
    try {
      await api.deleteProject(projectId);
      await loadProjects();
    } catch (caught) {
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
    defaultMaxSteps: "",
    defaultTimeoutSeconds: "",
    defaultCaptureScreenshots: true,
    parameters: "{}",
  };
}
