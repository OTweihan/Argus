/**
 * 项目/任务 Prompt 业务扩展的拆合工具。
 *
 * 后端约定：`parameters.prompt_extensions = {planner?: string; evaluator?: string}`。
 * 前端为了把扩展字段独立编辑，需要在表单加载/保存时与其它扁平参数互相分离。
 */

export const PROMPT_EXTENSIONS_KEY = "prompt_extensions";

export type PromptRole = "planner" | "evaluator";

export interface PromptExtensions {
    planner: string;
    evaluator: string;
}

/** 空扩展默认值（编辑器双向绑定与默认表单都用它）。 */
export function emptyPromptExtensions(): PromptExtensions {
    return {planner: "", evaluator: ""};
}

/**
 * 从 parameters 中提取 prompt_extensions 子结构。
 * 支持 string / null / 非法类型，统一兜底为空串。
 */
export function extractPromptExtensions(
    parameters: Record<string, unknown> | null | undefined,
): PromptExtensions {
    const result = emptyPromptExtensions();
    const raw = parameters?.[PROMPT_EXTENSIONS_KEY];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        return result;
    }
    const obj = raw as Record<string, unknown>;
    if (typeof obj.planner === "string") result.planner = obj.planner;
    if (typeof obj.evaluator === "string") result.evaluator = obj.evaluator;
    return result;
}

/**
 * 把 prompt_extensions 写回 parameters。
 *
 * - 不修改原 parameters，返回新对象
 * - 任一角色为空白字符串则不写入该字段
 * - 两个角色都为空白时，从 parameters 里彻底删除 prompt_extensions key
 */
export function mergePromptExtensions(
    parameters: Record<string, unknown>,
    extensions: PromptExtensions,
): Record<string, unknown> {
    const next: Record<string, unknown> = {...parameters};
    const planner = (extensions.planner ?? "").trim();
    const evaluator = (extensions.evaluator ?? "").trim();
    if (!planner && !evaluator) {
        delete next[PROMPT_EXTENSIONS_KEY];
        return next;
    }
    const payload: Record<string, string> = {};
    if (planner) payload.planner = planner;
    if (evaluator) payload.evaluator = evaluator;
    next[PROMPT_EXTENSIONS_KEY] = payload;
    return next;
}

/**
 * 把 parameters 拆成"剩余键值"与"prompt_extensions 子结构"，
 * 用于表单"参数键值列表"避免把扩展字段重复展示。
 */
export function splitParametersFromPromptExtensions(
    parameters: Record<string, unknown> | null | undefined,
): {rest: Record<string, unknown>; promptExtensions: PromptExtensions} {
    const promptExtensions = extractPromptExtensions(parameters);
    const rest: Record<string, unknown> = {};
    if (parameters) {
        for (const [key, value] of Object.entries(parameters)) {
            if (key === PROMPT_EXTENSIONS_KEY) continue;
            rest[key] = value;
        }
    }
    return {rest, promptExtensions};
}

/** 判断扩展是否真有内容（trim 后非空）。详情页据此决定是否折叠。 */
export function hasAnyExtension(extensions: PromptExtensions): boolean {
    return Boolean((extensions.planner ?? "").trim()) ||
        Boolean((extensions.evaluator ?? "").trim());
}
