/**
 * The appliance's backups as the administrator sees them (suveryn-tracker#33): what GET /v1/admin/backups
 * says, turned into one state. The backup service runs nightly; a success older than two days means the
 * nights since failed or didn't run.
 */
import type { BackupStatus } from "../api";

export type BackupState =
  | { kind: "unavailable" }                                  // no backup service has run (not an appliance yet)
  | { kind: "not_set_up" }                                   // the office chose "later"
  | { kind: "never"; failing: BackupStatus["last_error"] }   // set up, nothing written yet
  | { kind: "ok" | "stale" | "failing"; status: BackupStatus };

export const STALE_HOURS = 48;

export function backupState(s: BackupStatus | null, now: Date = new Date()): BackupState {
  if (!s || !s.available) return { kind: "unavailable" };
  if (!s.configured) return { kind: "not_set_up" };
  if (!s.last_success) return { kind: "never", failing: s.last_error ?? null };
  const failedSince = s.last_error && s.last_error.at > s.last_success.at;
  if (now.getTime() - Date.parse(s.last_success.at) > STALE_HOURS * 3600_000) return { kind: "stale", status: s };
  return { kind: failedSince ? "failing" : "ok", status: s };
}

/** How often the office should test its recovery key: a lost key shows only on the day of a restore. */
export const KEY_TEST_DAYS = 90;
const DAY = 24 * 3600_000;

export type KeyTestState =
  | { kind: "testing" }
  | { kind: "never" }                                                        // no test since backups began
  | { kind: "failed" | "ok" | "due"; test: NonNullable<BackupStatus["key_test"]> };

export function keyTestState(s: BackupStatus, now: Date = new Date()): KeyTestState {
  if (s.key_testing) return { kind: "testing" };
  const t = s.key_test;
  if (!t) return { kind: "never" };
  if (!t.ok) return { kind: "failed", test: t };
  return { kind: now.getTime() - Date.parse(t.at) > KEY_TEST_DAYS * DAY ? "due" : "ok", test: t };
}

/** What an administrator should be told outside the Backups page, most serious first; null: nothing.
 * Backups not set up, failing or two days old; then the key test failed, or due (none in the first
 * week of backups, then every three months). */
export type BackupAttention = "not_set_up" | "stale" | "failing" | "key_failed" | "key_due";

export function backupAttention(s: BackupStatus | null, now: Date = new Date()): BackupAttention | null {
  const state = backupState(s, now);
  if (state.kind === "not_set_up") return "not_set_up";
  if (state.kind === "stale") return "stale";
  if (state.kind === "failing" || (state.kind === "never" && state.failing)) return "failing";
  if (state.kind !== "ok") return null;
  const key = keyTestState(state.status, now);
  if (key.kind === "failed") return "key_failed";
  const since = state.status.last_success?.oldest ?? state.status.last_success?.at;
  if (key.kind === "due" || (key.kind === "never" && since && now.getTime() - Date.parse(since) > 7 * DAY)) return "key_due";
  return null;
}

/** "1.2 GB", "340 MB": a backup's size, decimal units as disks are sold; in French in octets ("188 ko"). */
export function sizeLabel(bytes: number, locale: string): string {
  const units = locale.startsWith("fr") ? ["o", "ko", "Mo", "Go", "To"] : ["B", "kB", "MB", "GB", "TB"];
  let n = bytes, i = 0;
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
  return `${n.toLocaleString(locale, { maximumFractionDigits: n < 10 && i > 0 ? 1 : 0 })} ${units[i]}`;
}
