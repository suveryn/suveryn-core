/**
 * Administration › Backups (suveryn-tracker#33): the last backup, the last failure, and what is on the
 * target, as the appliance's backup service recorded them (GET /v1/admin/backups; lib/backups.ts).
 */
import { AlertCircle, AlertTriangle, Check, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { getBackups, type BackupStatus } from "../api";
import { locale, useT } from "../i18n";
import { backupState, sizeLabel } from "../lib/backups";
import { InlineNotice, Rows } from "../ui";

const when = (iso: string) => new Date(iso).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" });

export function AdminBackups() {
  const m = useT();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getBackups().then(setStatus).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{m.backupsUnreadable(error)}</InlineNotice>;
  if (!status) return null;
  const state = backupState(status);
  const reason = (step: string) => m.backupStep[step as keyof typeof m.backupStep] ?? m.backupStep.other;
  return (
    <>
      <p className="view-intro">{m.adminBackupsIntro}</p>
      {state.kind === "unavailable" && <InlineNotice icon={<Info size={14} />}>{m.backupsUnavailable}</InlineNotice>}
      {state.kind === "not_set_up" && <InlineNotice icon={<AlertTriangle size={14} />} tone="error">{m.backupsNotSetUp}</InlineNotice>}
      {state.kind === "never" && (state.failing
        ? <InlineNotice icon={<AlertTriangle size={14} />} tone="error" alert>{m.backupFailed(when(state.failing.at), reason(state.failing.step))}</InlineNotice>
        : <InlineNotice icon={<Info size={14} />}>{m.backupsNever}</InlineNotice>)}
      {(state.kind === "ok" || state.kind === "stale" || state.kind === "failing") && (() => {
        const s = state.status, ok = s.last_success!;
        return (
          <>
            {state.kind === "ok" && <InlineNotice icon={<Check size={14} />}>{m.backupLast(when(ok.at), sizeLabel(ok.size, locale()))}</InlineNotice>}
            {state.kind !== "ok" && (
              <InlineNotice icon={<AlertTriangle size={14} />} tone="error" alert>
                {state.kind === "stale" ? m.backupStale(when(ok.at)) : m.backupFailed(when(s.last_error!.at), reason(s.last_error!.step))}
              </InlineNotice>
            )}
            <Rows rows={[
              ...(state.kind !== "ok" ? [{ label: m.backupLastGood, value: `${when(ok.at)} · ${sizeLabel(ok.size, locale())}` }] : []),
              ...(s.target ? [{ label: m.backupWhere, value: s.target === "usb" ? m.backupUsb : m.backupShare }] : []),
              ...(ok.on_target != null ? [{ label: m.backupOnTarget, value: m.backupCount(ok.on_target, ok.oldest ? when(ok.oldest) : null) }] : []),
              ...(s.retention_days != null ? [{ label: m.backupKept, value: m.backupDays(s.retention_days) }] : []),
            ]} />
          </>
        );
      })()}
      <p className="caption">{m.backupsCaption}</p>
    </>
  );
}
