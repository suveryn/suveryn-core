/**
 * Administration › Backups, the part that changes them (docs/design/admin.md, artboard 36): *Back up now* with
 * when the next one runs; where the backups are (the USB disk, or a share with its *Test connection*, with the
 * web setup's cards, fields and strings); *Every day at* and *Retention*; and the recovery sheet, with *Make a
 * new recovery key…*.
 *
 * The gateway can't change the appliance's backups itself: each change is a request the appliance's backup
 * service acts on (askBackupService), checked there as the web setup checks it. A share's test signs in and
 * writes a test file. The recovery key is made in this browser, as in the setup: only its public half goes to
 * the appliance, so the appliance can write backups and never read them. Old backups stay where they were.
 */
import { AlertCircle, Check, CircleCheck, Download, FolderSync, HardDrive, KeyRound, Play, Printer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  askBackupService, type BackupDisk, type BackupRetention, type BackupSettings, type BackupStatus,
} from "../api";
import { locale, useT } from "../i18n";
import { sizeLabel } from "../lib/backups";
import { canMakeRecoveryKey, makeRecoveryKey, recoveryKeyFile, type RecoveryKey } from "../setup/recoveryKey";
import { useText } from "../setup/i18n";
import {
  Button, Checkbox, Dialog, InlineNotice, PasswordField, RadioCards, SelectField, TextButton, TextField,
} from "../ui";

const RETENTIONS: BackupRetention[] = [14, 30, 90, 365];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

const hourLabel = (h: number) => new Date(2026, 0, 1, h).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });

/** "Next: tonight at 02:00." The night runs from 18:00 to 06:00. */
export function nextRunText(nextUtc: string, m: ReturnType<typeof useT>, now = new Date()): string {
  const next = new Date(nextUtc);
  const time = next.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  const night = next.getHours() >= 18 || next.getHours() < 6;
  const sameDay = next.toDateString() === now.toDateString();
  if (night && (sameDay || next.getHours() < 6)) return m.backupNextTonight(time);
  return sameDay ? m.backupNextToday(time) : m.backupNextTomorrow(time);
}

/** The recovery key's public half, shortened as on the key file's "# public key:" line, to compare. */
export const keyFingerprint = (recipient: string) => `${recipient.slice(0, 10)}…${recipient.slice(-8)}`;

type Form = {
  target: "usb" | "share"; disk: string; protocol: "smb" | "nfs"; address: string; user: string; password: string;
  retention: BackupRetention; hour: number;
};

function formFrom(s: BackupSettings | null | undefined): Form {
  return {
    target: s?.target ?? "usb", disk: s?.disk ?? "", protocol: s?.protocol ?? "smb", address: s?.address ?? "",
    user: s?.user ?? "", password: "", retention: s?.retention_days ?? 30, hour: s?.hour ?? 2,
  };
}

export function BackUpNow({ status, onStarted }: { status: BackupStatus; onStarted: () => void }) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const running = status.running_since;
  const start = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const a = await askBackupService({ kind: "run" }, 30);
      if (a.ok) { setStarted(true); onStarted(); } else setProblem(m.backupServiceSilent);
    } catch (e) { setProblem((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="backup-now">
      <Button variant="primary" onPress={start} isDisabled={busy || !!running}><Play size={14} aria-hidden /> {m.backUpNow}</Button>
      <span className="caption" role="status">
        {running ? m.backupRunning(new Date(running).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" }))
          : started ? m.backupStarted
          : status.settings?.next_run ? nextRunText(status.settings.next_run, m) : ""}
      </span>
      {problem && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{problem}</InlineNotice>}
    </div>
  );
}

export function BackupSettingsForm({ status, onSaved }: { status: BackupStatus; onSaved: () => void }) {
  const m = useT();
  const t = useText();
  const saved = status.settings ?? null;
  const [form, setForm] = useState<Form>(() => formFrom(saved));
  useEffect(() => { setForm(formFrom(saved)); }, [saved]);
  const set = <K extends keyof Form>(key: K) => (value: Form[K]) => { setForm((f) => ({ ...f, [key]: value })); setDone(false); setErrors({}); };
  const [disks, setDisks] = useState<BackupDisk[] | null>(null);
  const [looking, setLooking] = useState(false);
  const [test, setTest] = useState<{ state: "none" | "testing" | "ok" | "failed"; for?: string; message?: string }>({ state: "none" });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  // A new key is needed only when none is in use yet (backups never set up).
  const [key, setKey] = useState<RecoveryKey | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [stored, setStored] = useState(false);

  const lookForDisks = async () => {
    setLooking(true);
    try {
      const a = await askBackupService({ kind: "disks" }, 30);
      setDisks(a.disks ?? []);
      setForm((f) => (f.disk || !a.disks?.length ? f : { ...f, disk: a.disks[0].id }));
    } catch { setDisks([]); } finally { setLooking(false); }
  };
  useEffect(() => { if (form.target === "usb" && disks === null) lookForDisks(); }, [form.target]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!saved) canMakeRecoveryKey().then((ok) => { if (ok) makeRecoveryKey().then(setKey); });
  }, [saved]);

  const sameShare = saved?.target === "share" && saved.protocol === form.protocol && saved.address === form.address.trim()
    && (saved.user ?? "") === form.user.trim();
  const keepPassword = form.protocol === "smb" && sameShare && saved!.has_password && form.password === "";
  const shareKey = `${form.protocol} ${form.address.trim()} ${form.user.trim()} ${form.password}`;
  const shareChanged = form.target === "share" && !(sameShare && form.password === "");
  const tested = test.state === "ok" && test.for === shareKey;
  const changed = useMemo(() => {
    const was = formFrom(saved);
    return !saved || (Object.keys(form) as (keyof Form)[]).some((k) => k !== "password" && form[k] !== was[k]) || form.password !== "";
  }, [form, saved]);

  const runTest = async () => {
    setTest({ state: "testing" });
    try {
      const a = await askBackupService({ kind: "test-share", protocol: form.protocol, address: form.address.trim(),
        ...(form.protocol === "smb" ? { user: form.user.trim() || null, password: form.password || null, keep_password: keepPassword } : {}) }, 60);
      setTest(a.ok ? { state: "ok", for: shareKey } : { state: "failed", message: t.errors[a.error as keyof typeof t.errors] ?? t.errUnexpected });
    } catch { setTest({ state: "failed", message: t.errUnexpected }); }
  };

  const download = () => {
    if (!key) return;
    const name = window.location.hostname;
    const text = recoveryKeyFile(key, { name, id: null }, new Date(), { title: t.keyFileTitle, keep: t.keyFileKeep });
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    Object.assign(document.createElement("a"), { href: url, download: `suveryn-backup-recovery-key-${name}.txt` }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setDownloaded(true);
  };

  const save = async () => {
    const problems: Record<string, string> = {};
    if (form.target === "usb" && !form.disk) problems.disk = t.noDisk;
    if (form.target === "share") {
      if (!form.address.trim()) problems.address = t.errShareAddressMissing;
      else if (form.protocol === "smb" && !form.user.trim()) problems.user = t.errShareUserMissing;
      else if (shareChanged && !tested) problems.test = t.errTestFirst;
    }
    if (!saved) {
      if (!key) problems.key = t.noWebCrypto;
      else if (!downloaded) problems.key = t.errDownloadFirst;
      else if (!stored) problems.key = t.errConfirmStored;
    }
    setErrors(problems);
    if (Object.keys(problems).length) return;
    setBusy(true);
    try {
      const a = await askBackupService({
        kind: "settings", target: form.target, retention_days: form.retention, hour: form.hour,
        ...(form.target === "usb" ? { disk: form.disk } : {
          protocol: form.protocol, address: form.address.trim(), user: form.protocol === "smb" ? form.user.trim() || null : null,
          ...(form.protocol === "smb" ? { password: form.password || null, keep_password: keepPassword } : {}),
        }),
        ...(!saved && key ? { recipient: key.recipient } : {}),
      });
      if (a.ok) { setDone(true); setForm((f) => ({ ...f, password: "" })); onSaved(); }
      else setErrors(Object.fromEntries(Object.entries(a.errors ?? { _: a.error ?? "" }).map(([field, code]) =>
        [field, t.errors[code as keyof typeof t.errors] ?? t.errUnexpected])));
    } catch (e) { setErrors({ _: (e as Error).message }); } finally { setBusy(false); }
  };

  const diskOptions = [
    ...(disks ?? []).map((d) => ({ id: d.id, label: `${d.name} · ${sizeLabel(d.size_bytes, locale())}` })),
    ...(form.disk && !(disks ?? []).some((d) => d.id === form.disk) ? [{ id: form.disk, label: form.disk }] : []),
  ];
  return (
    <section aria-labelledby="backup-where" className="backup-settings">
      <h2 id="backup-where" className="label">{saved ? m.whereBackupsAre : m.setUpBackups}</h2>
      {!saved && <p className="caption">{m.diskFails}</p>}
      <RadioCards label={m.whereBackupsAre} name="target" value={form.target} onChange={(v) => set("target")(v as Form["target"])}
                  choices={[
                    { value: "usb", title: t.usbDisk, description: t.usbDiskDesc, icon: <HardDrive size={18} /> },
                    { value: "share", title: t.networkShare, description: t.networkShareDesc, icon: <FolderSync size={18} /> },
                  ]} />
      <div className="backup-settings-detail">
        {form.target === "usb" && (diskOptions.length ? (
          <div className="backup-disk-row">
            <SelectField name="disk" label={t.backupDisk} value={form.disk} onChange={set("disk")} options={diskOptions} />
            <TextButton onPress={lookForDisks} isDisabled={looking}>{t.lookAgain}</TextButton>
          </div>
        ) : (
          <div className="backup-disk-row">
            <p className="caption" role="status">{looking ? t.testing : t.noDisk}</p>
            <TextButton onPress={lookForDisks} isDisabled={looking}>{t.lookAgain}</TextButton>
          </div>
        ))}
        {form.target === "share" && (
          <>
            <SelectField name="protocol" label={t.shareType} value={form.protocol} onChange={(v) => set("protocol")(v as "smb" | "nfs")}
                         options={[{ id: "smb", label: t.smb }, { id: "nfs", label: t.nfs }]} />
            <TextField name="address" label={t.shareAddress} description={t.shareAddressHint} value={form.address}
                       onChange={set("address")} autoComplete="off"
                       placeholder={form.protocol === "smb" ? "\\\\nas.office.local\\backups" : "nas.office.local:/backups"} />
            {errors.address && <p className="ui-field-error">{errors.address}</p>}
            {form.protocol === "smb" && (
              <div className="backup-settings-row">
                <TextField name="user" label={t.shareUser} value={form.user} onChange={set("user")} autoComplete="off" />
                <PasswordField name="password" label={t.sharePassword} value={form.password} onChange={set("password")} autoComplete="off"
                               description={sameShare && saved!.has_password ? m.keepSavedPassword : undefined} />
              </div>
            )}
            {errors.user && <p className="ui-field-error">{errors.user}</p>}
            <div className="backup-test">
              <Button size="small" isDisabled={test.state === "testing"} onPress={runTest}>{t.testConnection}</Button>
              <span className="backup-test-status" role="status" data-state={tested ? "ok" : test.state === "failed" || errors.test ? "failed" : undefined}>
                {test.state === "testing" ? t.testing : tested ? t.testOk : test.state === "failed" ? test.message : errors.test ?? (shareChanged ? t.notTested : "")}
              </span>
            </div>
          </>
        )}
        {errors.disk && <p className="ui-field-error">{errors.disk}</p>}
        <div className="backup-settings-row">
          <SelectField name="hour" label={m.everyDayAt} value={String(form.hour)} onChange={(v) => set("hour")(Number(v))}
                       options={HOURS.map((h) => ({ id: String(h), label: hourLabel(h) }))} />
          <SelectField name="retention" label={m.retention} description={t.keepHint} value={String(form.retention)}
                       onChange={(v) => set("retention")(Number(v) as BackupRetention)}
                       options={RETENTIONS.map((d) => ({ id: String(d), label: t.days(d) }))} />
        </div>
        {saved && (saved.target !== form.target || (saved.disk ?? "") !== form.disk || (saved.address ?? "") !== form.address.trim()) && (
          <p className="caption">{saved.target === "usb" ? m.olderStayUsb : m.olderStayShare}</p>
        )}
      </div>
      {!saved && (
        <>
          <h3 className="label">{t.recoveryHeading}</h3>
          <p className="caption">{t.recoveryLead}</p>
          <KeyDownload ready={!!key} downloaded={downloaded} onDownload={download} />
          <Checkbox name="stored" checked={stored} onChange={setStored}>{t.recoveryConfirm}</Checkbox>
          {errors.key && <p className="ui-field-error">{errors.key}</p>}
        </>
      )}
      {(errors._ || errors.recipient || errors.retention_days || errors.hour) && (
        <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{errors._ || errors.recipient || errors.retention_days || errors.hour}</InlineNotice>
      )}
      <div className="admin-settings-save">
        <Button variant="primary" onPress={save} isDisabled={busy || !changed}>{busy ? m.saving : m.save}</Button>
        {done && <span className="caption status-ok"><Check size={12} aria-hidden /> {m.backupSettingsSaved}</span>}
      </div>
    </section>
  );
}

function KeyDownload({ ready, downloaded, onDownload }: { ready: boolean; downloaded: boolean; onDownload: () => void }) {
  const t = useText();
  return (
    <div className="backup-key">
      <span className="ui-fact-icon" aria-hidden><KeyRound size={18} /></span>
      <span className="backup-key-body">
        <span className="backup-key-title">{t.recoveryKey}</span>
        <span className="caption">{ready ? t.recoveryKeyDesc : t.noWebCrypto}</span>
      </span>
      <Button size="small" isDisabled={!ready} onPress={onDownload} aria-label={t.downloadLabel}>
        {downloaded ? <CircleCheck size={14} aria-hidden className="ui-icon-ok" /> : <Download size={14} aria-hidden />}
        {downloaded ? t.downloaded : t.download}
      </Button>
    </div>
  );
}

/** The recovery sheet, and a new key. The appliance holds only the public half, so the sheet shows what it
 *  knows and a box for where the key is kept; only right after a new key is made can it carry the key. */
export function RecoverySheet({ status, onSaved }: { status: BackupStatus; onSaved: () => void }) {
  const m = useT();
  const t = useText();
  const s = status.settings!;
  const [printing, setPrinting] = useState(false);
  const [newKey, setNewKey] = useState<{ key: RecoveryKey | null; downloaded: boolean; stored: boolean } | null>(null);
  const [fresh, setFresh] = useState<RecoveryKey | null>(null);  // the key just put in use: on the sheet, once
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const begin = async () => {
    setProblem(null);
    setNewKey({ key: null, downloaded: false, stored: false });
    if (await canMakeRecoveryKey()) {
      const key = await makeRecoveryKey();
      setNewKey((k) => (k ? { ...k, key } : k));
    }
  };
  const download = () => {
    if (!newKey?.key) return;
    const name = window.location.hostname;
    const text = recoveryKeyFile(newKey.key, { name, id: null }, new Date(), { title: t.keyFileTitle, keep: t.keyFileKeep });
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    Object.assign(document.createElement("a"), { href: url, download: `suveryn-backup-recovery-key-${name}.txt` }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNewKey({ ...newKey, downloaded: true });
  };
  const use = async () => {
    if (!newKey?.key) return;
    setBusy(true);
    setProblem(null);
    try {
      const a = await askBackupService({
        kind: "settings", target: s.target, retention_days: s.retention_days, hour: s.hour, recipient: newKey.key.recipient,
        ...(s.target === "usb" ? { disk: s.disk ?? "" } : { protocol: s.protocol ?? "smb", address: s.address ?? "", user: s.user,
                                                         keep_password: s.has_password }),
      });
      if (a.ok) { setFresh(newKey.key); setNewKey(null); onSaved(); } else setProblem(t.errUnexpected);
    } catch (e) { setProblem((e as Error).message); } finally { setBusy(false); }
  };
  const where = s.target === "usb" ? `${t.usbDisk}: ${s.disk ?? ""}` : `${t.networkShare}: ${s.address ?? ""}`;
  return (
    <section aria-labelledby="recovery-sheet">
      <h2 id="recovery-sheet" className="label">{m.recoverySheet}</h2>
      {fresh && <InlineNotice icon={<KeyRound size={14} />}>{m.newRecoveryKeySaved}</InlineNotice>}
      <div className="backup-sheet-actions">
        <Button size="small" onPress={() => setPrinting(true)}><Printer size={14} aria-hidden /> {m.printRecoverySheet}</Button>
        <TextButton onPress={begin}>{m.newRecoveryKey}</TextButton>
      </div>
      <Dialog isOpen={printing} onClose={() => setPrinting(false)} title={m.recoverySheet} actions={<>
        <TextButton onPress={() => setPrinting(false)}>{m.cancel}</TextButton>
        <Button variant="primary" onPress={() => window.print()}><Printer size={16} aria-hidden /> {m.printRecoverySheet}</Button>
      </>}>
        <div className="recovery-sheet">
          <h2>{m.recoverySheet}</h2>
          <dl>
            <dt>{m.sheetAppliance}</dt><dd>{window.location.hostname}</dd>
            <dt>{m.whereBackupsAre}</dt><dd>{where}</dd>
            <dt>{t.keyFingerprint}</dt><dd className="recovery-sheet-mono">{keyFingerprint(s.recipient)}</dd>
            <dt>{m.sheetMade}</dt><dd>{new Date().toLocaleDateString(locale(), { dateStyle: "long" })}</dd>
          </dl>
          {fresh
            ? <><p>{m.sheetWithKey}</p><p className="recovery-sheet-mono recovery-sheet-key">{fresh.identity}</p></>
            : <p>{m.sheetNoKey}</p>}
          <h3>{m.sheetRestoreTitle}</h3>
          <ol>{m.sheetRestoreSteps.map((step) => <li key={step}>{step}</li>)}</ol>
          <div className="recovery-sheet-kept">{m.keyKeptAt}</div>
        </div>
      </Dialog>
      <Dialog isOpen={newKey !== null} onClose={() => setNewKey(null)} busy={busy} title={m.newRecoveryKeyTitle} actions={<>
        <TextButton onPress={() => setNewKey(null)} isDisabled={busy}>{m.cancel}</TextButton>
        <Button variant="primary" onPress={use} isDisabled={busy || !newKey?.downloaded || !newKey?.stored}>
          {busy ? m.saving : m.newRecoveryKeySave}
        </Button>
      </>}>
        <p>{m.newRecoveryKeyText}</p>
        <KeyDownload ready={!!newKey?.key} downloaded={!!newKey?.downloaded} onDownload={download} />
        <Checkbox name="stored-new" checked={!!newKey?.stored} onChange={(v) => setNewKey((k) => (k ? { ...k, stored: v } : k))}>
          {t.recoveryConfirm}
        </Checkbox>
        {problem && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{problem}</InlineNotice>}
      </Dialog>
    </section>
  );
}
