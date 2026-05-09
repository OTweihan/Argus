import {reactive, ref, type Ref} from "vue";
import {ElMessageBox} from "element-plus";
import type {ProjectPayload} from "../api";
import {
    createProject as apiCreateProject,
    deleteProject as apiDeleteProject,
    listProjects as apiListProjects,
    updateProject as apiUpdateProject,
} from "../api";
import type {Project} from "../types";
import {errorMessage, nullableText, upsertById} from "../utils";

export interface ParamEntry {
    key: string;
    value: string;
}

export interface ProjectForm {
    editingId: string | null;
    name: string;
    description: string;
    baseUrl: string;
    gitUrl: string;
    authStateName: string;
    defaultMaxSteps: number | null;
    defaultTimeoutSeconds: number | null;
    defaultCaptureScreenshots: boolean;
    parameters: ParamEntry[];
}

export function useProjects(opts: {
    projects: Ref<Project[]>;
    error: Ref<string>;
    message: Ref<string>;
    formErrors: Record<string, string>;
}) {
    const {projects, error, message, formErrors} = opts;
    const projectForm = reactive<ProjectForm>(defaultProjectForm());
    const showProjectDialog = ref(false);

    async function loadProjects(): Promise<void> {
        const res = await apiListProjects();
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
        const gitUrl = nullableText(projectForm.gitUrl);
        if (gitUrl && !/^https?:\/\/.+/.test(gitUrl)) {
            formErrors.gitUrl = "请输入合法的 http/https URL";
            return;
        }
        let parameters: Record<string, unknown>;
        try {
            parameters = parseParamEntries(projectForm.parameters);
        } catch (caught) {
            formErrors.projectParameters = caught instanceof Error ? caught.message : "参数格式错误";
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
                ? await apiUpdateProject(projectForm.editingId, payload)
                : await apiCreateProject(payload);
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
            defaultMaxSteps: project.defaultMaxSteps ?? DEFAULT_MAX_STEPS,
            defaultTimeoutSeconds: project.defaultTimeoutSeconds ?? DEFAULT_TIMEOUT_S,
            defaultCaptureScreenshots: project.defaultCaptureScreenshots,
            parameters: dictToParamEntries(project.parameters),
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
            await apiDeleteProject(projectId);
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

const DEFAULT_MAX_STEPS = 20;
const DEFAULT_TIMEOUT_S = 300;

function defaultProjectForm(): ProjectForm {
    return {
        editingId: null,
        name: "",
        description: "",
        baseUrl: "",
        gitUrl: "",
        authStateName: "",
        defaultMaxSteps: DEFAULT_MAX_STEPS,
        defaultTimeoutSeconds: DEFAULT_TIMEOUT_S,
        defaultCaptureScreenshots: true,
        parameters: [],
    };
}

function parseParamEntries(entries: ParamEntry[]): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const entry of entries) {
        const key = entry.key.trim();
        if (!key) continue;
        if (key in result) {
            throw new Error(`参数键重复：${key}`);
        }
        result[key] = entry.value;
    }
    return result;
}

function dictToParamEntries(dict: Record<string, unknown>): ParamEntry[] {
    return Object.entries(dict).map(([key, value]) => ({
        key,
        value: typeof value === "string" ? value : JSON.stringify(value),
    }));
}
