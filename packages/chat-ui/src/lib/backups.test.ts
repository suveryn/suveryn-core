import { describe, expect, it } from "vitest";
import type { BackupStatus } from "../api";
import { backupAttention, backupState, keyTestState, sizeLabel } from "./backups";

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

  it("says when the recovery key should be tested, and tells the administrator outside the Backups page", () => {
    // review of the backup strategy: a lost key or a damaged backup showed only on the day of a restore
    expect(keyTestState({ ...base, key_testing: true }, now).kind).toBe("testing");
    expect(keyTestState(base, now).kind).toBe("never");
    const test = { at: "2026-10-01T10:00:00Z", ok: true, created: "2026-10-01T02:40:00Z" };
    expect(keyTestState({ ...base, key_test: test }, now).kind).toBe("ok");
    expect(keyTestState({ ...base, key_test: { ...test, at: "2026-07-01T10:00:00Z" } }, now).kind).toBe("due");
    expect(keyTestState({ ...base, key_test: { ...test, ok: false, step: "decrypt" } }, now).kind).toBe("failed");

    expect(backupAttention(null, now)).toBeNull();
    expect(backupAttention({ ...base, configured: false }, now)).toBe("not_set_up");
    expect(backupAttention(base, new Date("2026-10-25T09:00:00Z"))).toBe("stale");
    expect(backupAttention({ ...base, last_error: { at: "2026-10-23T02:41:00Z", step: "space", message: "full" } }, now)).toBe("failing");
    expect(backupAttention({ ...base, last_success: null, last_error: { at: "2026-10-23T02:41:00Z", step: "target", message: "x" } }, now)).toBe("failing");
    expect(backupAttention(base, now)).toBe("key_due");  // a month of backups and never tested
    expect(backupAttention({ ...base, last_success: { ...ok, oldest: "2026-10-20T02:31:00Z" } }, now)).toBeNull();  // the first week
    expect(backupAttention({ ...base, key_test: test }, now)).toBeNull();
    expect(backupAttention({ ...base, key_test: { ...test, ok: false } }, now)).toBe("key_failed");
    expect(backupAttention({ ...base, key_test: { ...test, at: "2026-07-01T10:00:00Z" } }, now)).toBe("key_due");
  });

  it("doesn't mark the key failing for one wrong file: the last test that passed stands (VM regression 03c8f74, finding 4)", () => {
    const wrong = { at: "2026-10-22T10:00:00Z", ok: false, step: "key", last_ok: "2026-10-22T09:50:00Z" };
    const k = keyTestState({ ...base, key_test: wrong }, now);
    expect(k).toMatchObject({ kind: "wrong_file", lastOk: "2026-10-22T09:50:00Z", due: false });
    expect(backupAttention({ ...base, key_test: wrong }, now)).toBeNull();  // nothing on Status
    expect(backupAttention({ ...base, key_test: { ...wrong, last_ok: "2026-07-01T10:00:00Z" } }, now)).toBe("key_due");
    expect(backupAttention({ ...base, key_test: { ...wrong, last_ok: null } }, now)).toBe("key_due");  // never passed, a month of backups
    expect(backupAttention({ ...base, key_test: { ...wrong, step: "read", last_ok: null } }, now)).toBe("key_failed");  // the backup itself
  });

  it("gives a backup's size in decimal units", () => {
    expect(sizeLabel(1_234_567_890, "en")).toBe("1.2 GB");
    expect(sizeLabel(340_000_000, "nl")).toBe("340 MB");
    expect(sizeLabel(999, "en")).toBe("999 B");
    expect(sizeLabel(188_432, "fr")).toBe("188 ko");  // VM check of #33: "kB" in French
  });
});
