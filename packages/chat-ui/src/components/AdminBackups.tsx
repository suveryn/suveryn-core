/**
 * Administration › Backups (suveryn-tracker#33): the last backup, the last failure, and what is on the
 * target, as the appliance's backup service recorded them (GET /v1/admin/backups; lib/backups.ts). And
 * the recovery key test (review of the backup strategy, 26 October 2026): the appliance can't read its
 * own backups, so the administrator gives the key, and the appliance checks it opens the newest backup.
 * And changing them (docs/design/admin.md, artboard 36; AdminBackupSettings.tsx): back up now, where, when,
 * how long, and the recovery sheet.
 */
import { Check, CircleAlert, FileKey, Info, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getBackups, HttpError, testRecoveryKey, type BackupStatus } from "../api";
import { locale, useT } from "../i18n";
import { backupState, keyTestState, sizeLabel } from "../lib/backups";
import { Button, FileButton, InlineNotice, readText, Rows } from "../ui";
import { BackUpNow, BackupSettingsForm, RecoverySheet } from "./AdminBackupSettings";

const when = (iso: string) => new Date(iso).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" });

export function AdminBackups() {
  const m = useT();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keyProblem, setKeyProblem] = useState<string | null>(null);
  const load = useCallback(() => getBackups().then(setStatus).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  // While a key test or a backup runs, the status is read again every few seconds.
  const busy = !!status?.key_testing || !!status?.running_since;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [busy, load]);
  const test = async (files: File[]) => {
    setKeyProblem(null);
    const key = files[0] ? await readText(files[0], 4096) : null;
    if (key === null) { setKeyProblem(m.keyTestNotKey); return; }
    try {
      await testRecoveryKey(key);
      setStatus((s) => (s ? { ...s, key_testing: true } : s));
    } catch (e) {
      setKeyProblem(e instanceof HttpError && e.status === 415 ? m.keyTestNotKey : (e as Error).message);
    }
  };
  if (error) return <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{m.backupsUnreadable(error)}</InlineNotice>;
  if (!status) return null;
  const state = backupState(status);
  const reason = (step: string) => m.backupStep[step as keyof typeof m.backupStep] ?? m.backupStep.other;
  return (
    <>
      <p className="view-intro">{m.adminBackupsIntro}</p>
      {status.settings && <BackUpNow status={status} onStarted={load} />}
      {state.kind === "unavailable" && <InlineNotice icon={<Info size={14} />}>{m.backupsUnavailable}</InlineNotice>}
      {state.kind === "not_set_up" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error">{m.backupsNotSetUp}</InlineNotice>}
      {state.kind === "never" && (state.failing
        ? <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>{m.backupFailed(when(state.failing.at), reason(state.failing.step))}</InlineNotice>
        : <InlineNotice icon={<Info size={14} />}>{m.backupsNever}</InlineNotice>)}
      {(state.kind === "ok" || state.kind === "stale" || state.kind === "failing") && (() => {
        const s = state.status, ok = s.last_success!;
        return (
          <>
            {state.kind === "ok" && <InlineNotice icon={<Check size={14} />} tone="ok">{m.backupLast(when(ok.at), sizeLabel(ok.size, locale()))}</InlineNotice>}
            {state.kind !== "ok" && (
              <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>
                {state.kind === "stale" ? m.backupStale(when(ok.at)) : m.backupFailed(when(s.last_error!.at), reason(s.last_error!.step))}
              </InlineNotice>
            )}
            <Rows rows={[
              ...(state.kind !== "ok" ? [{ label: m.backupLastGood, value: `${when(ok.at)} · ${sizeLabel(ok.size, locale())}` }] : []),
              ...(ok.on_target != null ? [{ label: m.backupOnTarget, value: m.backupCount(ok.on_target, ok.oldest ? when(ok.oldest) : null) }] : []),
              ...(ok.disk ? [{ label: m.backupDisk, value: ok.disk }] : []),
            ]} />
            {s.target === "usb" && <p className="caption">{m.backupRotate}</p>}
            <h2 className="label">{m.keyTestTitle}</h2>
            <p className="view-intro">{m.keyTestIntro}</p>
            <KeyTest status={s} problem={keyProblem} onTest={test} />
          </>
        );
      })()}
      <BackupSettingsForm status={status} onSaved={load} />
      {status.settings && <RecoverySheet status={status} onSaved={load} />}
      <p className="caption">{m.backupsCaption}</p>
    </>
  );
}

function KeyTest({ status, problem, onTest }: { status: BackupStatus; problem: string | null; onTest: (files: File[]) => void }) {
  const m = useT();
  const k = keyTestState(status);
  return (
    <>
      {k.kind === "testing" && <InlineNotice icon={<Info size={14} />}>{m.keyTesting}</InlineNotice>}
      {k.kind === "never" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error">{m.keyTestNever}</InlineNotice>}
      {k.kind === "ok" && <InlineNotice icon={<Check size={14} />} tone="ok">{m.keyTestOk(when(k.test.at))}</InlineNotice>}
      {k.kind === "due" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error">{m.keyTestDue(when(k.test.at))}</InlineNotice>}
      {k.kind === "failed" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>{m.keyTestFailed}</InlineNotice>}
      {problem && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{problem}</InlineNotice>}
      {k.kind !== "testing" && (
        <FileButton accept={[".txt", ".key"]} onSelect={onTest}>
          <Button size="small" variant="secondary"><FileKey size={14} aria-hidden /> {m.keyTestButton}</Button>
        </FileButton>
      )}
    </>
  );
}
