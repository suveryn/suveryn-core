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

/** "1.2 GB", "340 MB": a backup's size, decimal units as disks are sold. */
export function sizeLabel(bytes: number, locale: string): string {
  const units = ["B", "kB", "MB", "GB", "TB"];
  let n = bytes, i = 0;
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
  return `${n.toLocaleString(locale, { maximumFractionDigits: n < 10 && i > 0 ? 1 : 0 })} ${units[i]}`;
}
