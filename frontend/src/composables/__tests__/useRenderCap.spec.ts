import { describe, expect, it } from "vitest";
import { ref } from "vue";

import { RENDER_CAP, useRenderCap } from "../useRenderCap";

describe("useRenderCap", () => {
  it("未触限时原样透传", () => {
    const source = ref([1, 2, 3]);
    const { visibleItems, hiddenCount } = useRenderCap(source);

    expect(visibleItems.value).toEqual([1, 2, 3]);
    expect(hiddenCount.value).toBe(0);
  });

  it("触顶时只渲染前 RENDER_CAP 条并统计隐藏数量", () => {
    const source = Array.from({ length: RENDER_CAP + 3 }, (_, i) => i);
    const { visibleItems, hiddenCount } = useRenderCap(source);

    expect(visibleItems.value).toHaveLength(RENDER_CAP);
    expect(visibleItems.value[0]).toBe(0);
    expect(visibleItems.value[RENDER_CAP - 1]).toBe(RENDER_CAP - 1);
    expect(hiddenCount.value).toBe(3);
  });

  it("响应式源变化后重新截断", () => {
    const source = ref<number[]>([]);
    const { visibleItems, hiddenCount } = useRenderCap(source);

    source.value = Array.from({ length: RENDER_CAP + 1 }, (_, i) => i);

    expect(visibleItems.value).toHaveLength(RENDER_CAP);
    expect(hiddenCount.value).toBe(1);
  });

  it("支持 getter 源与自定义上限", () => {
    const items = [1, 2, 3, 4, 5];
    const { visibleItems, hiddenCount } = useRenderCap(() => items, 2);

    expect(visibleItems.value).toEqual([1, 2]);
    expect(hiddenCount.value).toBe(3);
  });
});
