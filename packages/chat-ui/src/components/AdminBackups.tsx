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
import { FileButton, InlineNotice, readText, TextButton } from "../ui";
import { backupWhen } from "./AdminStatus";
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
  if (error) return <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{m.backupsUnreadable({ why: error })}</InlineNotice>;
  if (!status) return null;
  const state = backupState(status);
  const reason = (step: string) => m.backupStep[step as keyof typeof m.backupStep] ?? m.backupStep.other;
  return (
    <>
      {state.kind === "unavailable" && <InlineNotice icon={<Info size={14} />}>{m.backupsUnavailable}</InlineNotice>}
      {state.kind === "not_set_up" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error">{m.backupsNotSetUp}</InlineNotice>}
      {state.kind === "never" && (state.failing
        ? <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>{m.backupFailed({ when: when(state.failing.at), why: reason(state.failing.step) })}</InlineNotice>
        : <InlineNotice icon={<Info size={14} />}>{m.backupsNever}</InlineNotice>)}
      {(state.kind === "ok" || state.kind === "stale" || state.kind === "failing") && (() => {
        const s = state.status, ok = s.last_success!;
        // short, as on board B11: the size and how many there are
        const detail = [sizeLabel(ok.size, locale()), ok.on_target != null ? m.backupCount({ n: ok.on_target }) : null].filter(Boolean).join(" · ");
        return (
          <>
            {state.kind !== "ok" && (
              <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>
                {state.kind === "stale" ? m.backupStale({ when: when(ok.at) }) : m.backupFailed({ when: when(s.last_error!.at), why: reason(s.last_error!.step) })}
              </InlineNotice>
            )}
            {/* two cards first: the last backup, and the recovery key (board B11) */}
            <div className="backup-cards">
              <section className="backup-card" aria-labelledby="backup-last">
                <h2 id="backup-last" className="backup-card-label">
                  {state.kind === "ok" ? <Check size={13} aria-hidden /> : <TriangleAlert size={13} aria-hidden />} {m.backupLastHeading}
                </h2>
                <p className="backup-card-value">{backupWhen(ok.at, m)}</p>
                <p className="backup-card-detail">{detail}</p>
              </section>
              <section className="backup-card" aria-labelledby="backup-key">
                <h2 id="backup-key" className="backup-card-label"><FileKey size={13} aria-hidden /> {m.keyTestTitle}</h2>
                <KeyTest status={s} problem={keyProblem} onTest={test} />
              </section>
            </div>
          </>
        );
      })()}
      {status.settings && <BackUpNow status={status} onStarted={load} />}
      <BackupSettingsForm status={status} onSaved={load} />
      {status.settings && <RecoverySheet status={status} onSaved={load} />}
    </>
  );
}

function KeyTest({ status, problem, onTest }: { status: BackupStatus; problem: string | null; onTest: (files: File[]) => void }) {
  const m = useT();
  const k = keyTestState(status);
  const day = (iso: string) => new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "short" });
  // Board B11: the key's state in a few words, large, and "Nu testen" as a link under it.
  const value = k.kind === "testing" ? m.keyTesting : k.kind === "never" ? m.keyCardNever : k.kind === "ok" ? m.keyCardOk({ day: day(k.test.at) })
    : k.kind === "due" ? m.keyCardDue({ day: day(k.test.at) }) : k.kind === "failed" ? m.keyCardFailed
    : k.kind === "wrong_file" && k.lastOk ? (k.due ? m.keyCardDue({ day: day(k.lastOk) }) : m.keyCardOk({ day: day(k.lastOk) })) : m.keyCardNever;
  return (
    <>
      <p className="backup-card-value" role="status">{value}</p>
      {k.kind === "wrong_file" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>{m.keyTestFailed}</InlineNotice>}
      {k.kind === "failed" && <InlineNotice icon={<TriangleAlert size={14} />} tone="error" alert>{m.keyTestBroken}</InlineNotice>}
      {problem && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{problem}</InlineNotice>}
      {k.kind !== "testing" && (
        <FileButton accept={[".txt", ".key"]} onSelect={onTest}>
          <TextButton link aria-label={m.keyTestButton}>{m.testNow}</TextButton>
        </FileButton>
      )}
    </>
  );
}
