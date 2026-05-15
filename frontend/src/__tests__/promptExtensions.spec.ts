import {describe, expect, it} from "vitest";

import {
    PROMPT_EXTENSIONS_KEY,
    emptyPromptExtensions,
    extractPromptExtensions,
    hasAnyExtension,
    mergePromptExtensions,
    splitParametersFromPromptExtensions,
} from "../promptExtensions";

describe("promptExtensions.extractPromptExtensions", () => {
    it("空 parameters 返回空扩展", () => {
        expect(extractPromptExtensions(null)).toEqual({planner: "", evaluator: ""});
        expect(extractPromptExtensions(undefined)).toEqual({planner: "", evaluator: ""});
        expect(extractPromptExtensions({})).toEqual({planner: "", evaluator: ""});
    });

    it("从 parameters 中正确取出 planner / evaluator", () => {
        const ext = extractPromptExtensions({
            [PROMPT_EXTENSIONS_KEY]: {planner: "P", evaluator: "E"},
            other: 1,
        });
        expect(ext).toEqual({planner: "P", evaluator: "E"});
    });

    it("非法类型兜底为空串", () => {
        expect(extractPromptExtensions({[PROMPT_EXTENSIONS_KEY]: "not-an-object"}))
            .toEqual({planner: "", evaluator: ""});
        expect(extractPromptExtensions({[PROMPT_EXTENSIONS_KEY]: ["x"]}))
            .toEqual({planner: "", evaluator: ""});
        expect(extractPromptExtensions({[PROMPT_EXTENSIONS_KEY]: {planner: 123}}))
            .toEqual({planner: "", evaluator: ""});
    });
});

describe("promptExtensions.mergePromptExtensions", () => {
    it("两侧非空时写入 prompt_extensions 字段，不修改原对象", () => {
        const original = {foo: 1};
        const merged = mergePromptExtensions(original, {planner: "P", evaluator: "E"});
        expect(merged).toEqual({foo: 1, [PROMPT_EXTENSIONS_KEY]: {planner: "P", evaluator: "E"}});
        expect(original).toEqual({foo: 1});
    });

    it("空白扩展会被过滤；保留有效角色", () => {
        const merged = mergePromptExtensions({}, {planner: "   ", evaluator: "E"});
        expect(merged[PROMPT_EXTENSIONS_KEY]).toEqual({evaluator: "E"});
    });

    it("两个角色都为空白时彻底删除 key", () => {
        const merged = mergePromptExtensions(
            {[PROMPT_EXTENSIONS_KEY]: {planner: "old"}, foo: 1},
            {planner: "", evaluator: " \n "},
        );
        expect(merged).toEqual({foo: 1});
        expect(merged).not.toHaveProperty(PROMPT_EXTENSIONS_KEY);
    });

    it("往返不丢失数据（extract → merge）", () => {
        const start = {
            foo: "bar",
            [PROMPT_EXTENSIONS_KEY]: {planner: "P", evaluator: "E"},
        };
        const ext = extractPromptExtensions(start);
        const restored = mergePromptExtensions({foo: "bar"}, ext);
        expect(restored).toEqual(start);
    });
});

describe("promptExtensions.splitParametersFromPromptExtensions", () => {
    it("把扁平参数和扩展分开", () => {
        const {rest, promptExtensions} = splitParametersFromPromptExtensions({
            modelConfigId: "m-1",
            [PROMPT_EXTENSIONS_KEY]: {planner: "P"},
            other: 42,
        });
        expect(rest).toEqual({modelConfigId: "m-1", other: 42});
        expect(promptExtensions).toEqual({planner: "P", evaluator: ""});
    });

    it("空 parameters 同样安全", () => {
        const {rest, promptExtensions} = splitParametersFromPromptExtensions(null);
        expect(rest).toEqual({});
        expect(promptExtensions).toEqual(emptyPromptExtensions());
    });
});

describe("promptExtensions.hasAnyExtension", () => {
    it("trim 后非空才视为有效", () => {
        expect(hasAnyExtension({planner: "", evaluator: ""})).toBe(false);
        expect(hasAnyExtension({planner: "   ", evaluator: ""})).toBe(false);
        expect(hasAnyExtension({planner: "x", evaluator: ""})).toBe(true);
        expect(hasAnyExtension({planner: "", evaluator: "y"})).toBe(true);
    });
});
