/** 参数条目（键值对列表）与 Record 互转工具。 */

export interface ParamEntry {
    key: string;
    value: string;
}

/** 将参数条目列表转换为 Record，检测重复键。 */
export function parseParamEntries(entries: ParamEntry[]): Record<string, unknown> {
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

/** 将 Record 转换为参数条目列表。 */
export function dictToParamEntries(dict: Record<string, unknown>): ParamEntry[] {
    return Object.entries(dict).map(([key, value]) => ({
        key,
        value: typeof value === "string" ? value : JSON.stringify(value),
    }));
}
