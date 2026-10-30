/**
 * Administration › Status (docs/design/admin.md, artboards 30 and 39): what needs attention, each with the
 * button that fixes it; the six checks in plain words (the clock: kept by a time server, or how far off by the
 * browsers, with "Set to this PC's time" when it is far off and no time server keeps it) ("Working" in teal with its check, or an ink cross and
 * since when); and an overview. Counts only, never what is asked or read. Read again every minute while open.
 */
import { AlertCircle, AlertTriangle, Brain, Check, Clock, Database, DatabaseBackup, FileText, HardDrive, Lock, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { applianceClockAnswer, getAdminStatus, getBackups, setApplianceClock, type AdminStatus as Status, type BackupStatus,
  type StatusCheck } from "../api";
import { locale, useT } from "../i18n";
import { backupAttention, sizeLabel } from "../lib/backups";
import { measureClock, type Measured } from "../lib/clock";
import { Button, Dialog, InlineNotice, Notice, TextButton } from "../ui";
import type { AdminPage } from "./Admin";

const ICON: Record<StatusCheck["id"], ReactNode> = {
  answering: <Brain size={16} aria-hidden />, reading: <FileText size={16} aria-hidden />, signin: <Lock size={16} aria-hidden />,
  data: <Database size={16} aria-hidden />, disk: <HardDrive size={16} aria-hidden />, clock: <Clock size={16} aria-hidden />,
};
const CLOCK_WARN_MS = 10_000; // as the gateway's clock.WARN_MS: codes fail from about 30 s

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

  // This PC against the appliance's clock, for "Set to this PC's time" (lib/clock.ts)
  const [thisPc, setThisPc] = useState<Measured | null>(null);
  const clockCheck = status?.checks.find((c) => c.id === "clock");
  const clockSynced = clockCheck?.synced === true;
  useEffect(() => {
    if (clockCheck && !clockSynced) measureClock().then(setThisPc).catch(() => setThisPc(null));
  }, [clockCheck?.offset_ms, clockSynced, clockCheck]);

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
                    ? <span className="status-ok"><Check size={14} aria-hidden />{" "}
                        {c.id === "disk" ? m.statusEnough : c.id === "clock" ? m.statusOnTime : m.statusWorking}</span>
                    : <span className="status-warn">{c.id === "disk"
                        ? <><AlertTriangle size={14} aria-hidden /> {m.statusAlmostFull}</>
                        : c.id === "clock" && c.offset_ms != null
                        ? <><AlertTriangle size={14} aria-hidden /> {offLabel(c.offset_ms, m)}</>
                        : <><XCircle size={14} aria-hidden /> {m.notWorkingSince(clock(c.since ?? status.checked_at))}</>}</span>}
                </li>
              ))}
            </ul>
            {reading && !reading.ok && <p className="caption">{m.readStillWorks}</p>}
            {clockCheck && !clockSynced && thisPc && Math.abs(thisPc.offset_ms) >= CLOCK_WARN_MS && (
              <SetClock offset={thisPc.offset_ms} onDone={load} />
            )}
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

function offLabel(offset: number, m: ReturnType<typeof useT>): string {
  const s = Math.round(Math.abs(offset) / 1000);
  return offset > 0 ? m.clockAhead(s) : m.clockBehind(s);
}

/** "Set to this PC's time", for a difference too large to be nudged: a confirmation with both times, then the
 *  appliance's answer (it sets nothing while a time server keeps the clock, or for more than a year). */
function SetClock({ offset, onDone }: { offset: number; onDone: () => void }) {
  const m = useT();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const hms = (ms: number) => new Date(ms).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const now = Date.now();
  const failed = (code: string | null) => ({ ok: false, text: m.clockSetFailed(m.clockErrors[code ?? "other"] ?? m.clockErrors.other) });
  const set = async () => {
    setBusy(true);
    try {
      const measured = await measureClock(); // again: the difference as it is now, not when the page opened
      if (!measured) throw new Error("not measured");
      let answer = await setApplianceClock(measured);
      for (let i = 0; answer.pending && i < 30; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        answer = await applianceClockAnswer(answer.id);
      }
      setOutcome(answer.ok ? { ok: true, text: m.clockSetDone } : failed(answer.pending ? "other" : answer.error));
    } catch {
      setOutcome(failed("other"));
    }
    setBusy(false);
    setOpen(false);
    onDone();
  };
  return (
    <>
      <p className="caption">
        {m.clockThisPc(offLabel(offset, m))}{" "}
        <Button size="small" onPress={() => { setOutcome(null); setOpen(true); }}><Clock size={14} aria-hidden /> {m.clockSet}</Button>
      </p>
      {outcome && <InlineNotice tone={outcome.ok ? "ok" : "error"} alert={!outcome.ok}
                                icon={outcome.ok ? <Check size={14} /> : <AlertCircle size={14} />}>{outcome.text}</InlineNotice>}
      <Dialog isOpen={open} onClose={() => setOpen(false)} busy={busy} title={m.clockSetTitle} actions={<>
        <TextButton onPress={() => setOpen(false)} isDisabled={busy}>{m.cancel}</TextButton>
        <Button variant="primary" onPress={set} isDisabled={busy}>{busy ? m.clockSetting : m.clockSet}</Button>
      </>}>
        <p>{m.clockSetBody(hms(now + offset), hms(now))}</p>
        <p className="caption">{m.clockSetCheck}</p>
      </Dialog>
    </>
  );
}

function detail(c: StatusCheck, m: ReturnType<typeof useT>): string {
  if (c.id === "answering" && c.in_progress) return m.nInProgress(c.in_progress);
  if (c.id === "reading") {
    return [c.in_progress ? m.nInProgress(c.in_progress) : "", c.waiting ? m.nWaiting(c.waiting) : ""].filter(Boolean).join(" · ");
  }
  if (c.id === "disk" && c.free != null && c.total != null) return m.freeOf(sizeLabel(c.free, locale()), sizeLabel(c.total, locale()));
  if (c.id === "clock") return c.synced ? m.clockKeptByServer : c.offset_ms != null && c.ok ? `${m.clockByBrowsers} · ${offLabel(c.offset_ms, m)}` : m.clockByBrowsers;
  return "";
}
