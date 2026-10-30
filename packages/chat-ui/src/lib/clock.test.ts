import { describe, expect, it } from "vitest";
import { difference, quickest } from "./clock";

describe("the appliance's clock against this PC's", () => {
  it("counts the middle of the round trip, not its delay", () => {
    // sent at 1000, answered with 6050, back at 1100: the appliance is 5 s ahead of the middle (1050)
    expect(difference(1000, 6050, 1100)).toEqual({ offset_ms: 5000, rtt_ms: 100 });
    expect(difference(1000, 1050 - 95_000, 1100).offset_ms).toBe(-95_000); // behind
  });

  it("keeps the quickest round trip", () => {
    expect(quickest([{ offset_ms: 4000, rtt_ms: 300 }, { offset_ms: 4100, rtt_ms: 20 }, { offset_ms: 3900, rtt_ms: 90 }]))
      .toEqual({ offset_ms: 4100, rtt_ms: 20 });
    expect(quickest([])).toBeNull();
  });
});
