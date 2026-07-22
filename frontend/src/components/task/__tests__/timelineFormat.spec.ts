import { describe, expect, it } from "vitest";

import {
  eventTypeLabel,
  hasTimelineData,
  isTimelineEvent,
  phaseColor,
  phaseLabel,
  prettyTimelineJson,
} from "../timelineFormat";

describe("timeline formatting", () => {
  it("maps known labels and keeps unknown values", () => {
    expect(phaseLabel("planner")).toBe("规划器");
    expect(phaseLabel("custom")).toBe("custom");
    expect(eventTypeLabel("complete")).toBe("完成");
    expect(phaseColor("custom")).toBe("#909399");
  });

  it("validates timeline event shape and serializes data", () => {
    expect(isTimelineEvent({eventId: "e1", taskId: "t1"})).toBe(true);
    expect(isTimelineEvent({eventId: "e1"})).toBe(false);
    expect(hasTimelineData({value: 1})).toBe(true);
    expect(hasTimelineData({})).toBe(false);
    expect(prettyTimelineJson({value: 1})).toContain('"value": 1');
  });
});
