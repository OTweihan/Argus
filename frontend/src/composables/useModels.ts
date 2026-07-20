import {reactive, ref, type Ref} from "vue";
import {ElMessageBox} from "element-plus";
import type {ModelConfigPayload, ModelConnectionPayload} from "../api";
import {
    createModel as apiCreateModel,
    deleteModel as apiDeleteModel,
    listModels as apiListModels,
    testModel as apiTestModel,
    updateModel as apiUpdateModel,
} from "../api";
import type {ModelConfig} from "../types";
import {clearFormErrors, errorMessage, nullableText, sortBy} from "../utils";

export interface ModelForm {
    editingId: string | null;
    name: string;
    provider: string;
    model: string;
    apiKey: string;
    baseUrl: string;
    maxRetries: number | null;
    timeoutSeconds: number | null;
    isDefault: boolean;
    enabled: boolean;
}

interface DialogState {
    title: string;
    message: string;
    tone: "success" | "error" | "info";
}

export function useModels(opts: {
    models: Ref<ModelConfig[]>;
    error: Ref<string>;
    message: Ref<string>;
    formErrors: Record<string, string>;
    dialog: Ref<DialogState | null>;
}) {
    const {models, error, message, formErrors, dialog} = opts;
    const modelForm = reactive<ModelForm>(defaultModelForm());
    const showModelDialog = ref(false);

    async function loadModels(): Promise<void> {
        const res = await apiListModels(true);
        models.value = sortBy(res.models ?? [], (m) => (m.isDefault ? 0 : 1));
    }

    async function saveModel(): Promise<void> {
        clearFormErrors(formErrors);
        if (!String(modelForm.name).trim()) {
            formErrors.modelName = "名称不能为空";
            return;
        }
        if (!String(modelForm.provider).trim()) {
            formErrors.modelProvider = "供应商不能为空";
            return;
        }
        if (!String(modelForm.model).trim()) {
            formErrors.modelModel = "模型不能为空";
            return;
        }
        if (!String(modelForm.apiKey).trim()) {
            formErrors.modelApiKey = "API密钥不能为空";
            return;
        }
        if (!String(modelForm.baseUrl).trim()) {
            formErrors.modelBaseUrl = "基础URL不能为空";
            return;
        }
        try {
            const payload = readModelPayload();
            await (modelForm.editingId
                ? apiUpdateModel(modelForm.editingId, payload)
                : apiCreateModel(payload));
            await loadModels();
            const wasEditing = Boolean(modelForm.editingId);
            showModelDialog.value = false;
            resetModelForm();
            message.value = wasEditing ? "模型配置已更新。" : "模型配置已创建。";
            error.value = "";
        } catch (caught) {
            error.value = errorMessage(caught);
            message.value = "";
        }
    }

    function editModel(model: ModelConfig): void {
        Object.assign(modelForm, {
            editingId: model.modelConfigId,
            name: model.name ?? "",
            provider: model.provider,
            model: model.model ?? "",
            apiKey: "",
            baseUrl: model.baseUrl,
            maxRetries: model.maxRetries,
            timeoutSeconds: model.timeoutSeconds,
            isDefault: model.isDefault,
            enabled: model.enabled,
        });
        error.value = "";
        clearFormErrors(formErrors);
        showModelDialog.value = true;
    }

    async function deleteModel(modelConfigId: string): Promise<void> {
        try {
            await ElMessageBox.confirm("确认删除这个模型配置？", "警告", {
                confirmButtonText: "删除",
                cancelButtonText: "取消",
                type: "warning",
            });
            await apiDeleteModel(modelConfigId);
            await loadModels();
        } catch (caught) {
            if (caught === "cancel") return;
            error.value = errorMessage(caught);
        }
    }

    async function testModel(modelConfigId: string): Promise<void> {
        try {
            if (!modelConfigId && !String(modelForm.model).trim()) {
                showDialog("模型连接检查失败", "请先填写模型名称。", "error");
                return;
            }
            const payload: ModelConnectionPayload = modelConfigId
                ? {modelConfigId, ...readModelPayload()}
                : readModelPayload();
            showDialog("模型连接检查", "正在测试模型连接...", "info");
            const result = await apiTestModel(payload);
            const detail = [
                result.message,
                result.model ? `模型：${result.model}` : "",
                result.latencyMs !== null ? `耗时：${result.latencyMs}ms` : "",
            ]
                .filter(Boolean)
                .join("\n");
            showDialog("模型连接检查通过", detail, "success");
        } catch (caught) {
            showDialog("模型连接检查失败", errorMessage(caught), "error");
        }
    }

    function openNewModelDialog(): void {
        resetModelForm();
        error.value = "";
        clearFormErrors(formErrors);
        showModelDialog.value = true;
    }

    function resetModelForm(): void {
        Object.assign(modelForm, defaultModelForm());
    }

    function readModelPayload(): ModelConfigPayload {
        const payload: ModelConfigPayload = {
            name: String(modelForm.name).trim(),
            provider: modelForm.provider,
            model: String(modelForm.model).trim(),
            apiKey: nullableText(modelForm.apiKey) ?? "",
            baseUrl: nullableText(modelForm.baseUrl),
            maxRetries: modelForm.maxRetries,
            timeoutSeconds: modelForm.timeoutSeconds,
            isDefault: modelForm.isDefault,
            enabled: modelForm.enabled,
        };
        return payload;
    }

    function showDialog(title: string, dialogMessage: string, tone: "success" | "error" | "info"): void {
        dialog.value = {title, message: dialogMessage, tone};
    }

    return {
        modelForm,
        showModelDialog,
        loadModels,
        saveModel,
        editModel,
        deleteModel,
        testModel,
        openNewModelDialog,
        resetModelForm,
    };
}

function defaultModelForm(): ModelForm {
    return {
        editingId: null,
        name: "",
        provider: "",
        model: "",
        apiKey: "",
        baseUrl: "",
        maxRetries: 5,
        timeoutSeconds: 120,
        isDefault: false,
        enabled: true,
    };
}
