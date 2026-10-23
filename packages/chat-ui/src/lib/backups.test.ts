import { describe, expect, it } from "vitest";
import type { BackupStatus } from "../api";
import { backupState, sizeLabel } from "./backups";

const now = new Date("2026-10-23T09:00:00Z");
const ok = { at: "2026-10-23T02:40:00Z", size: 1_234_567_890, on_target: 30, oldest: "2026-09-23T02:31:00Z" };
const base: BackupStatus = { available: true, configured: true, target: "usb", retention_days: 30, last_attempt: ok.at,
                             last_success: ok, last_error: null };

describe("the backups, as the administrator sees them (suveryn-tracker#33)", () => {
  it("says what there is to say, from nothing at all to a failing night", () => {
    expect(backupState(null, now).kind).toBe("unavailable");
    expect(backupState({ ...base, available: false }, now).kind).toBe("unavailable");
    expect(backupState({ ...base, configured: false }, now).kind).toBe("not_set_up");
    expect(backupState({ ...base, last_success: null }, now).kind).toBe("never");
    expect(backupState(base, now).kind).toBe("ok");
    const failed = { at: "2026-10-23T02:41:00Z", step: "target", message: "the backup disk isn't connected" };
    expect(backupState({ ...base, last_error: failed }, now).kind).toBe("failing");
    expect(backupState({ ...base, last_error: { ...failed, at: "2026-10-20T02:41:00Z" } }, now).kind).toBe("ok");  // fixed since
    expect(backupState(base, new Date("2026-10-25T09:00:00Z")).kind).toBe("stale");
  });

  it("gives a backup's size in decimal units", () => {
    expect(sizeLabel(1_234_567_890, "en")).toBe("1.2 GB");
    expect(sizeLabel(340_000_000, "nl")).toBe("340 MB");
    expect(sizeLabel(999, "en")).toBe("999 B");
    expect(sizeLabel(188_432, "fr")).toBe("188 ko");  // VM check of #33: "kB" in French
  });
});
