/**
 * Administration › Status (docs/design/admin.md, artboards 30 and 39): what needs attention, each with the
 * button that fixes it; the six checks in plain words (the clock: kept by a time server, or how far off by the
 * browsers, with "Set to this PC's time" when it is far off and no time server keeps it) ("Working" in teal with its check, or an ink cross and
 * since when); and an overview. Counts only, never what is asked or read. Read again every minute while open.
 */
import {
  Brain, Check, CircleAlert, CircleX, Clock, Database, DatabaseBackup, FileText, HardDrive, Lock, RefreshCw,
  TriangleAlert, Users
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { applianceClockAnswer, getAdminStatus, getBackups, listAccounts, setApplianceClock, type AdminStatus as Status, type BackupStatus,
  type StatusCheck, type UsersList } from "../api";
import { locale, useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { whole } from "../lib/usage";
import { backupAttentions, lastKeyTestOk, sizeLabel } from "../lib/backups";
import { measureClock, sendClock, type Measured } from "../lib/clock";
import { Button, Dialog, InlineNotice, Notice } from "../ui";
import type { AdminPage } from "./Admin";

const ICON: Record<StatusCheck["id"], ReactNode> = {
  answering: <Brain size={16} aria-hidden />, reading: <FileText size={16} aria-hidden />, signin: <Lock size={16} aria-hidden />,
  data: <Database size={16} aria-hidden />, disk: <HardDrive size={16} aria-hidden />, clock: <Clock size={16} aria-hidden />,
};
const CLOCK_WARN_MS = 10_000; // as the gateway's clock.WARN_MS: codes fail from about 30 s

const clock = (iso: string) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });

export function AdminStatus({ onOpen }: { onOpen: (page: AdminPage) => void }) {
  const m = useT();
  const [status, setStatus] = useState<Status | null>(null);
  const [backups, setBackups] = useState<BackupStatus | null>(null);
  const [users, setUsers] = useState<UsersList | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    try {
      setStatus(await getAdminStatus());
      setFailed(false);
    } catch {
      setFailed(true);
    }
    getBackups().then(setBackups).catch(() => setBackups(null));
    listAccounts().then(setUsers).catch(() => setUsers(null));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  // This PC against the appliance's clock, for "Set to this PC's time" (lib/clock.ts)
  const [thisPc, setThisPc] = useState<Measured | null>(null);
  // What setting the clock came to, kept here: the part that sets it goes once the clock is right, and its
  // notice went with it (VM regression e0f2e26, finding 3).
  const [clockOutcome, setClockOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const clockCheck = status?.checks.find((c) => c.id === "clock");
  const clockSynced = clockCheck?.synced === true;
  // The row said "on time" from the browsers' earlier reports while this PC measured 95 s (VM regression 03c8f74,
  // finding 6): this PC's measurement is reported (once per visit) and the checks are read again, and until the
  // gateway counts it the row says what this PC measured, so the row and the line under it agree.
  const reported = useRef(false);
  useEffect(() => {
    if (!clockCheck || clockSynced) return;
    measureClock().then((measured) => {
      setThisPc(measured);
      if (measured && clockCheck.ok && Math.abs(measured.offset_ms) >= CLOCK_WARN_MS && !reported.current) {
        reported.current = true;
        sendClock(measured).then(load).catch(() => undefined);
      }
    }).catch(() => setThisPc(null));
  }, [clockCheck?.offset_ms, clockSynced, clockCheck, load]);
  const pcOff = clockCheck ? thisPcOff(clockCheck, thisPc) : null;

  const attention = backupAttentions(backups);
  const counted = users ? users.users.filter((u) => u.enabled).length : null;
  const reading = status?.checks.find((c) => c.id === "reading");
  return (
    <>
      {/* Board B01: only when something needs it, one row per item with its action at the right */}
      {attention.length > 0 && (
        <section aria-labelledby="needs-attention">
          <h2 id="needs-attention" className="label">{m.needsAttention}</h2>
          <ul className="admin-attention">
            {attention.map((a) => (
              <li key={a}>
                <TriangleAlert size={16} aria-hidden />
                <span className="admin-attention-text"><b>{a === "key_due" ? keyDueLine(lastKeyTestOk(backups), m) : m.backupAttention[a]}</b></span>
                <Button size="small" onPress={() => onOpen("backups")}>{a === "key_due" || a === "key_failed" ? m.testNow : m.view}</Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="is-it-working">
        <h2 id="is-it-working" className="label">{m.isEverythingWorking}</h2>
        {failed && !status ? (
          <>
            <Notice icon={<CircleAlert size={16} />} title={m.statusUnavailable}>{m.tryingInAMinute}</Notice>
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
                  {c.id === "clock" && pcOff !== null
                    ? <span className="status-warn"><TriangleAlert size={14} aria-hidden /> {offLabel(pcOff, m)}</span>
                    : c.ok
                    ? <span className="status-ok"><Check size={14} aria-hidden />{" "}
                        {c.id === "disk" ? m.statusEnough : c.id === "clock" ? m.statusOnTime : m.statusWorking}</span>
                    : <span className="status-warn">{c.id === "disk"
                        ? <><TriangleAlert size={14} aria-hidden /> {m.statusAlmostFull}</>
                        : c.id === "clock" && c.offset_ms != null
                        ? <><TriangleAlert size={14} aria-hidden /> {offLabel(c.offset_ms, m)}</>
                        : <><CircleX size={14} aria-hidden /> {m.notWorkingSince({ time: clock(c.since ?? status.checked_at) })}</>}</span>}
                </li>
              ))}
            </ul>
            {reading && !reading.ok && <p className="caption">{m.readStillWorks}</p>}
            {clockCheck && !clockSynced && thisPc && Math.abs(thisPc.offset_ms) >= CLOCK_WARN_MS && (
              <SetClock offset={thisPc.offset_ms} onDone={load} onOutcome={setClockOutcome} />
            )}
            {clockOutcome && <InlineNotice tone={clockOutcome.ok ? "ok" : "error"} alert={!clockOutcome.ok} status={clockOutcome.ok}
                                           icon={clockOutcome.ok ? <Check size={14} /> : <CircleAlert size={14} />}>{clockOutcome.text}</InlineNotice>}
            <p className="caption">{m.checkedAt({ time: clock(status.checked_at) })}</p>
          </>
        )}
      </section>

      {(status?.version || backups?.last_success || counted !== null) && (
        <section aria-labelledby="status-overview">
          <h2 id="status-overview" className="label">{m.statusOverview}</h2>
          <div className="admin-overview">
            {status?.version && (
              <div className="admin-tile"><span className="admin-tile-label"><RefreshCw size={14} aria-hidden /> {m.statusVersion}</span>
                <b>{status.version}</b></div>
            )}
            {backups?.last_success && (
              <div className="admin-tile"><span className="admin-tile-label"><DatabaseBackup size={14} aria-hidden /> {m.lastBackup}</span>
                <b>{backupWhen(backups.last_success.at, m)}{backups.target ? ` · ${backups.target === "usb" ? m.onUsbDisk : m.onNetworkShare}` : ""}</b></div>
            )}
            {counted !== null && (
              <div className="admin-tile"><span className="admin-tile-label"><Users size={14} aria-hidden /> {m.adminUsers}</span>
                <b>{users?.agreement_users ? m.usersTile({ n: counted, max: users.agreement_users }) : whole(counted)}</b></div>
            )}
          </div>
        </section>
      )}
    </>
  );
}

/** "Last night 02:14" for the small hours of today, else "Today 14:02", "Yesterday 02:14", "3 Nov 02:14". */
export function backupWhen(iso: string, m: ReturnType<typeof useT>): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  const now = new Date();
  const today = d.toDateString() === now.toDateString();
  return `${today && d.getHours() < 6 ? m.lastNight : dayLabel(iso)} ${time}`;
}

/** This PC's difference with the appliance when the row would say "on time" from the browsers' earlier reports but
 *  this PC measures it off (VM regression 03c8f74, finding 6); null when they agree, or a time server keeps it. */
export function thisPcOff(c: StatusCheck, thisPc: Measured | null): number | null {
  return c.ok && !c.synced && thisPc !== null && Math.abs(thisPc.offset_ms) >= CLOCK_WARN_MS ? thisPc.offset_ms : null;
}

function offLabel(offset: number, m: ReturnType<typeof useT>): string {
  const s = Math.round(Math.abs(offset) / 1000);
  return offset > 0 ? m.clockAhead({ s }) : m.clockBehind({ s });
}

/** "Set to this PC's time", for a difference too large to be nudged: a confirmation with both times, then the
 *  appliance's answer (it sets nothing while a time server keeps the clock, or for more than a year). */
function SetClock({ offset, onDone, onOutcome }: { offset: number; onDone: () => void; onOutcome: (o: { ok: boolean; text: string } | null) => void }) {
  const m = useT();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const hms = (ms: number) => new Date(ms).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const now = Date.now();
  const failed = (code: string | null) => ({ ok: false, text: m.clockSetFailed({ why: m.clockErrors[code ?? "other"] ?? m.clockErrors.other }) });
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
      onOutcome(answer.ok ? { ok: true, text: m.clockSetDone } : failed(answer.pending ? "other" : answer.error));
    } catch {
      onOutcome(failed("other"));
    }
    setBusy(false);
    setOpen(false);
    onDone();
  };
  return (
    <>
      <p className="caption">
        {m.clockThisPc({ difference: offLabel(offset, m) })}{" "}
        <Button size="small" onPress={() => { onOutcome(null); setOpen(true); }}><Clock size={14} aria-hidden /> {m.clockSet}</Button>
      </p>
      <Dialog isOpen={open} onClose={() => setOpen(false)} busy={busy} kind="confirmation" risky title={m.clockSetTitle}
              cancel={{ label: m.cancel }} primary={{ label: m.clockSet, onPress: () => void set(), busyLabel: m.clockSetting }}>
        <p>{m.clockSetBody({ appliance: hms(now + offset), pc: hms(now) })}</p>
        <p className="caption">{m.clockSetCheck}</p>
      </Dialog>
    </>
  );
}

function detail(c: StatusCheck, m: ReturnType<typeof useT>): string {
  if (c.id === "answering" && c.in_progress) return m.nInProgress({ n: c.in_progress });
  if (c.id === "reading") {
    return [c.in_progress ? m.nInProgress({ n: c.in_progress }) : "", c.waiting ? m.nWaiting({ n: c.waiting }) : ""].filter(Boolean).join(" · ");
  }
  if (c.id === "disk" && c.free != null && c.total != null) return m.freeOf({ free: sizeLabel(c.free, locale()), total: sizeLabel(c.total, locale()) });
  if (c.id === "clock") return c.synced ? m.clockKeptByServer : m.clockByBrowsers; // the offset only when it is off, in the status column
  return "";
}

/** The recovery key's line in *Needs attention* (board B01): when it last opened a backup, as the page writes dates
 *  ("21 July", with the year when it isn't this one), or that it never did; and how often to test it. */
export function keyDueLine(lastOk: string | null, m: ReturnType<typeof useT>, now: Date = new Date()): string {
  if (!lastOk) return m.keyNeverTested;
  const d = new Date(lastOk);
  return m.keyNotTestedSince({ day: d.toLocaleDateString(locale(), { day: "numeric", month: "long",
                                                           ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) }) });
}
