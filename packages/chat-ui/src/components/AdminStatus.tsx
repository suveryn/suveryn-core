/**
 * Administration › Status (docs/design/admin.md, artboards 30 and 39): what needs attention, each with the
 * button that fixes it; the five checks in plain words ("Working" in teal with its check, or an ink cross and
 * since when); and an overview. Counts only, never what is asked or read. Read again every minute while open.
 */
import { AlertCircle, AlertTriangle, Brain, Check, Database, DatabaseBackup, FileText, HardDrive, Lock, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { getAdminStatus, getBackups, type AdminStatus as Status, type BackupStatus, type StatusCheck } from "../api";
import { locale, useT } from "../i18n";
import { backupAttention, sizeLabel } from "../lib/backups";
import { Button, Notice } from "../ui";
import type { AdminPage } from "./Admin";

const ICON: Record<StatusCheck["id"], ReactNode> = {
  answering: <Brain size={16} aria-hidden />, reading: <FileText size={16} aria-hidden />, signin: <Lock size={16} aria-hidden />,
  data: <Database size={16} aria-hidden />, disk: <HardDrive size={16} aria-hidden />,
};

const clock = (iso: string) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
const when = (iso: string) => new Date(iso).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" });

export function AdminStatus({ onOpen }: { onOpen: (page: AdminPage) => void }) {
  const m = useT();
  const [status, setStatus] = useState<Status | null>(null);
  const [backups, setBackups] = useState<BackupStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    try {
      setStatus(await getAdminStatus());
      setFailed(false);
    } catch {
      setFailed(true);
    }
    getBackups().then(setBackups).catch(() => setBackups(null));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const attention = backupAttention(backups);
  const reading = status?.checks.find((c) => c.id === "reading");
  return (
    <>
      {attention && (
        <section aria-labelledby="needs-attention">
          <h2 id="needs-attention" className="label">{m.needsAttention}</h2>
          <ul className="admin-attention">
            <li>
              <AlertTriangle size={16} aria-hidden />
              <span className="admin-attention-text"><b>{m.backupAttention[attention]}</b></span>
              <Button size="small" onPress={() => onOpen("backups")}>{m.backupAttentionOpen}</Button>
            </li>
          </ul>
        </section>
      )}

      <section aria-labelledby="is-it-working">
        <h2 id="is-it-working" className="label">{m.isEverythingWorking}</h2>
        {failed && !status ? (
          <>
            <Notice icon={<AlertCircle size={16} />} title={m.statusUnavailable}>{m.tryingInAMinute}</Notice>
            <Button size="small" onPress={load}><RefreshCw size={14} aria-hidden /> {m.tryAgain}</Button>
          </>
        ) : !status ? (
          <ul className="admin-checks" aria-busy="true">
            {[0, 1, 2].map((i) => <li key={i} className="admin-check admin-skeleton" aria-hidden><span /><span /></li>)}
          </ul>
        ) : (
          <>
            <ul className="admin-checks">
              {status.checks.map((c) => (
                <li key={c.id} className="admin-check">
                  <span className="admin-check-icon">{ICON[c.id]}</span>
                  <span className="admin-check-name">
                    {m.checkName[c.id]}
                    {detail(c, m) && <span className="admin-check-detail">{detail(c, m)}</span>}
                  </span>
                  {c.ok
                    ? <span className="status-ok"><Check size={14} aria-hidden /> {c.id === "disk" ? m.statusEnough : m.statusWorking}</span>
                    : <span className="status-warn">{c.id === "disk"
                        ? <><AlertTriangle size={14} aria-hidden /> {m.statusAlmostFull}</>
                        : <><XCircle size={14} aria-hidden /> {m.notWorkingSince(clock(c.since ?? status.checked_at))}</>}</span>}
                </li>
              ))}
            </ul>
            {reading && !reading.ok && <p className="caption">{m.readStillWorks}</p>}
            <p className="caption">{m.checkedAt(clock(status.checked_at))}</p>
          </>
        )}
      </section>

      {(status?.version || backups?.last_success) && (
        <section aria-labelledby="status-overview">
          <h2 id="status-overview" className="label">{m.statusOverview}</h2>
          <div className="admin-overview">
            {status?.version && (
              <div className="admin-tile"><span className="admin-tile-label"><RefreshCw size={14} aria-hidden /> {m.statusVersion}</span>
                <b>{status.version}</b></div>
            )}
            {backups?.last_success && (
              <div className="admin-tile"><span className="admin-tile-label"><DatabaseBackup size={14} aria-hidden /> {m.lastBackup}</span>
                <b>{when(backups.last_success.at)}</b></div>
            )}
          </div>
        </section>
      )}
    </>
  );
}

function detail(c: StatusCheck, m: ReturnType<typeof useT>): string {
  if (c.id === "answering" && c.in_progress) return m.nInProgress(c.in_progress);
  if (c.id === "reading") {
    return [c.in_progress ? m.nInProgress(c.in_progress) : "", c.waiting ? m.nWaiting(c.waiting) : ""].filter(Boolean).join(" · ");
  }
  if (c.id === "disk" && c.free != null && c.total != null) return m.freeOf(sizeLabel(c.free, locale()), sizeLabel(c.total, locale()));
  return "";
}
