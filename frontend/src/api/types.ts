
import type {components} from "./openapi.gen";

/** @description 创建项目请求 */
export type ProjectPayload = components["schemas"]["ProjectCreateRequest"];

/** @description 创建任务请求 */
export type TaskPayload = components["schemas"]["TaskCreateRequest"];

/** @description 创建模型配置请求 */
export type ModelConfigPayload = components["schemas"]["ModelConfigCreateRequest"];

/** @description 模型连接检查请求 */
export type ModelConnectionPayload = components["schemas"]["ModelConfigTestRequest"];

/** @description Prompt 扩展拼接预览请求 */
export type PromptPreviewPayload = components["schemas"]["PromptPreviewRequest"];

/** @description Prompt 扩展拼接预览响应 */
export type PromptPreviewResponse = components["schemas"]["PromptPreviewResponse"];
