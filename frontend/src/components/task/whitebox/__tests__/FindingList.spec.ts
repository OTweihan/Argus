import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { FindingInfo } from "../../../../api/task";
import FindingList from "../FindingList.vue";

function finding(findingId: string, title: string, severity: string): FindingInfo {
  return {
    findingId,
    title,
    severity,
    description: `${title} description`,
  } as unknown as FindingInfo;
}

describe("FindingList", () => {
  it("按照严重程度从高到低展示，同级保持原有顺序", () => {
    const wrapper = mount(FindingList, {
      props: {
        items: [
          finding("low-1", "低风险", "LOW"),
          finding("high-1", "高风险一", "HIGH"),
          finding("medium-1", "中风险", "MEDIUM"),
          finding("high-2", "高风险二", "HIGH"),
          finding("info-1", "提示项", "INFO"),
        ],
        total: 5,
        hasMore: false,
        loading: false,
      },
    });

    expect(wrapper.find(".sort-indicator").text()).toContain("高 → 中 → 低");
    expect(wrapper.findAll(".finding-item h4").map((item) => item.text())).toEqual([
      "高风险一",
      "高风险二",
      "中风险",
      "低风险",
      "提示项",
    ]);
  });
});
