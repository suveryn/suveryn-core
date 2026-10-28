import { describe, expect, it } from "vitest";
import { keyFingerprint, nextRunText } from "../components/AdminBackupSettings";
import { TABLES_FOR_TESTS } from "../i18n";

const m = TABLES_FOR_TESTS.en;

describe("Administration › Backups", () => {
  it("says when the next backup runs: tonight, today or tomorrow", () => {
    const at = (d: number, h: number) => new Date(2026, 9, d, h, 0).toISOString();
    const now = new Date(2026, 9, 29, 10, 0);
    expect(nextRunText(at(30, 2), m, now)).toMatch(/^Next: tonight at 0?2:00/);
    expect(nextRunText(at(29, 23), m, now)).toMatch(/^Next: tonight at 23:00/);
    expect(nextRunText(at(29, 13), m, now)).toMatch(/^Next: today at 13:00/);
    expect(nextRunText(at(30, 9), m, now)).toMatch(/^Next: tomorrow at 0?9:00/);
  });

  it("shortens the recovery key's public half as the key file's line can be compared with it", () => {
    const recipient = "age1" + "qpzry9x8gf2tvdw0s3jn54khce6mua7l".repeat(2).slice(0, 58);
    expect(keyFingerprint(recipient)).toBe(`${recipient.slice(0, 10)}…${recipient.slice(-8)}`);
  });
});
