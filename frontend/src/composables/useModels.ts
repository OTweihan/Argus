import { reactive, ref, type Ref } from "vue";
import { api, type ModelConfigPayload, type ModelConnectionPayload } from "../api";
import type { ModelConfig, ModelProvider, TaskType } from "../types";
import { errorMessage, nullableNumber, nullableText } from "../utils";

interface ModelForm {
  editingId: string | null;
  name: string;
  provider: ModelProvider;
  model: string;
  apiKey: string;
  baseUrl: string;
  completionsPath: string;
  maxTokens: string;
  temperature: string;
  maxRetries: string;
  timeoutSeconds: string;
  taskType: "" | TaskType;
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
  const { models, error, message, formErrors, dialog } = opts;
  const modelForm = reactive<ModelForm>(defaultModelForm());
  const showModelDialog = ref(false);

  const providers: ModelProvider[] = ["dashscope", "openai", "ollama", "custom"];

  async function loadModels(): Promise<void> {
    const res = await api.listModels(true);
    models.value = res.models;
  }

  async function saveModel(): Promise<void> {
    clearFormErrors();
    if (!String(modelForm.name).trim()) {
      formErrors.modelName = "名称不能为空";
      return;
    }
    if (!String(modelForm.model).trim()) {
      formErrors.modelModel = "模型不能为空";
      return;
    }
    try {
      const payload = readModelPayload();
      const model = modelForm.editingId
        ? await api.updateModel(modelForm.editingId, payload)
        : await api.createModel(payload);
      models.value = upsertById(models.value, model, "modelConfigId");
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
      completionsPath: model.completionsPath,
      maxTokens: String(model.maxTokens),
      temperature: String(model.temperature),
      maxRetries: String(model.maxRetries),
      timeoutSeconds: String(model.timeoutSeconds),
      taskType: model.taskType ?? "",
      isDefault: model.isDefault,
      enabled: model.enabled,
    });
    error.value = "";
    clearFormErrors();
    showModelDialog.value = true;
  }

  async function deleteModel(modelConfigId: string): Promise<void> {
    if (!window.confirm("确认删除这个模型配置？")) return;
    try {
      await api.deleteModel(modelConfigId);
      await loadModels();
    } catch (caught) {
      error.value = errorMessage(caught);
    }
  }

  async function testModel(modelConfigId: string): Promise<void> {
    try {
      if (!modelConfigId && !String(modelForm.model).trim()) {
        showDialog("模型连接检查失败", "请先填写模型名称。", "error");
        return;
      }
      const payload: ModelConnectionPayload = modelConfigId ? { modelConfigId } : readModelPayload();
      showDialog("模型连接检查", "正在测试模型连接...", "info");
      const result = await api.testModel(payload);
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
    clearFormErrors();
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
      baseUrl: nullableText(modelForm.baseUrl),
      completionsPath: nullableText(modelForm.completionsPath),
      maxTokens: nullableNumber(modelForm.maxTokens, "最大 Token"),
      temperature: nullableNumber(modelForm.temperature, "温度"),
      maxRetries: nullableNumber(modelForm.maxRetries, "重试次数"),
      timeoutSeconds: nullableNumber(modelForm.timeoutSeconds, "超时秒数"),
      taskType: modelForm.taskType || null,
      isDefault: modelForm.isDefault,
      enabled: modelForm.enabled,
    };
    const apiKey = nullableText(modelForm.apiKey);
    if (apiKey) payload.apiKey = apiKey;
    return payload;
  }

  function showDialog(title: string, dialogMessage: string, tone: "success" | "error" | "info"): void {
    dialog.value = { title, message: dialogMessage, tone };
  }

  function clearFormErrors(): void {
    for (const key of Object.keys(formErrors)) {
      delete formErrors[key];
    }
  }

  return {
    modelForm,
    showModelDialog,
    providers,
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
    provider: "dashscope",
    model: "",
    apiKey: "",
    baseUrl: "",
    completionsPath: "/chat/completions",
    maxTokens: "4096",
    temperature: "0.1",
    maxRetries: "3",
    timeoutSeconds: "60",
    taskType: "",
    isDefault: false,
    enabled: true,
  };
}

function upsertById<T extends Record<string, any>>(list: T[], item: T, idKey: string): T[] {
  const index = list.findIndex((existing) => existing[idKey] === item[idKey]);
  if (index >= 0) {
    const copy = [...list];
    copy[index] = item;
    return copy;
  }
  return [...list, item];
}
