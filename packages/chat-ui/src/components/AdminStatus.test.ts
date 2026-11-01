/** Status's clock row and the line under it agree (VM regression 03c8f74, finding 6). */
import { describe, expect, it } from "vitest";
import type { StatusCheck } from "../api";
import { thisPcOff } from "./AdminStatus";

describe("the clock row", () => {
  const row = { id: "clock", ok: true, synced: false } as StatusCheck;
  it("says what this PC measured while the browsers' earlier reports still say on time", () => {
    expect(thisPcOff(row, { offset_ms: -95_000, rtt_ms: 4 })).toBe(-95_000);
    expect(thisPcOff(row, { offset_ms: 2_000, rtt_ms: 4 })).toBeNull();          // on time here too
    expect(thisPcOff({ ...row, synced: true }, { offset_ms: -95_000, rtt_ms: 4 })).toBeNull();  // a time server keeps it
    expect(thisPcOff({ ...row, ok: false }, { offset_ms: -95_000, rtt_ms: 4 })).toBeNull();    // the row says it already
    expect(thisPcOff(row, null)).toBeNull();
  });
});
