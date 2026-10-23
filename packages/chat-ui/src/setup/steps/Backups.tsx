/**
 * Setup step 5: Backups (design web-05-backups*.html, suveryn-tracker#33). A USB disk on the
 * appliance, a share on the office network (tested first), or later. Retention, and the recovery key:
 * made in this browser (recoveryKey.ts), downloaded by the administrator, its public half sent to the
 * appliance with the answer, so the appliance can write backups but never read them.
 */
import { CircleCheck, Download, FolderSync, HardDrive, KeyRound, Clock, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Checkbox, Form, Notice, PasswordField, RadioCards, SelectField, TextField, useFieldError,
         type FieldErrors } from "../../ui";
import { getState, saveBackups, testShare, type BackupsAnswer, type Retention, type SetupState, type UsbDisk } from "../api";
import { canMakeRecoveryKey, makeRecoveryKey, recoveryKeyFile, type RecoveryKey } from "../recoveryKey";
import { LOCALES, useLang, useText } from "../i18n";
import { checkThenSave, StepFooter } from "./common";
import { sizeLabel } from "../../lib/backups";

type Target = "usb" | "share" | "later";
type Props = { state: SetupState; onBack: () => void; onDone: (b: BackupsAnswer) => void; headingId: string };

const RETENTIONS: Retention[] = [14, 30, 90, 365];

/** The key made in this page, kept when the step is left and opened again (Back, Edit on the Review),
 *  so the file already downloaded stays the right one. A reload makes a new key. */
let session: { key: RecoveryKey; downloaded: boolean; stored: boolean } | null = null;

/** "1 TB", "500 GB", in French "2,5 To": decimal units, as disks are sold (lib/backups.ts). */
export function diskSize(bytes: number, locale: string): string {
  return sizeLabel(bytes, locale);
}

export function Backups({ state, onBack, onDone, headingId }: Props) {
  const t = useText();
  const locale = LOCALES[useLang()];
  const saved = state.answers.backups;
  const [target, setTarget] = useState<Target>(saved?.target ?? "usb");
  const [disks, setDisks] = useState<UsbDisk[]>(state.usb_disks);
  const [disk, setDisk] = useState<string>(saved?.target === "usb" ? saved.disk : state.usb_disks[0]?.id ?? "");
  const [protocol, setProtocol] = useState<"smb" | "nfs">(saved?.target === "share" ? saved.protocol : "smb");
  const [address, setAddress] = useState(saved?.target === "share" ? saved.address : "");
  const [user, setUser] = useState(saved?.target === "share" ? saved.user ?? "" : "");
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<{ state: "none" | "testing" | "ok" | "failed"; for?: string; message?: string }>({ state: "none" });
  const [retention, setRetention] = useState<Retention>(saved && saved.target !== "later" ? saved.retention_days : 30);
  const [key, setKey] = useState<RecoveryKey | null>(session?.key ?? null);
  const [cryptoOk, setCryptoOk] = useState(true);
  const [downloaded, setDownloaded] = useState(session?.downloaded ?? false);
  const [stored, setStored] = useState(session?.stored ?? false);

  useEffect(() => {
    if (session) return;
    canMakeRecoveryKey().then((ok) => {
      setCryptoOk(ok);
      if (ok) makeRecoveryKey().then((k) => { session = { key: k, downloaded: false, stored: false }; setKey(k); });
    });
  }, []);
  useEffect(() => { if (session) Object.assign(session, { downloaded, stored }); }, [downloaded, stored]);

  const shareKey = `${protocol} ${address} ${user} ${password}`;
  const tested = test.state === "ok" && test.for === shareKey;

  const runTest = async () => {
    setTest({ state: "testing" });
    try {
      const r = await testShare({ protocol, address: address.trim(), ...(protocol === "smb" ? { user, password } : {}) });
      setTest(r.ok ? { state: "ok", for: shareKey } : { state: "failed", message: t.errors[r.error] ?? t.errUnexpected });
    } catch {
      setTest({ state: "failed", message: t.errUnexpected });
    }
  };

  const download = () => {
    if (!key) return;
    const text = recoveryKeyFile(key, { name: state.name, id: state.appliance?.id ?? null }, new Date(),
                                 { title: t.keyFileTitle, keep: t.keyFileKeep });
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `suveryn-backup-recovery-key-${state.name}.txt` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setDownloaded(true);
  };

  const answer = (): BackupsAnswer =>
    target === "later" ? { target }
      : target === "usb" ? { target, disk, retention_days: retention, recipient: key?.recipient ?? "" }
        : { target, protocol, address: address.trim(), user: protocol === "smb" ? user.trim() : null, retention_days: retention,
            recipient: key?.recipient ?? "" };

  const check = () => {
    const errors: FieldErrors = {};
    if (target === "share") {
      if (!address.trim()) errors.address = t.errShareAddressMissing;
      else if (protocol === "smb" && !user.trim()) errors.user = t.errShareUserMissing;
      else if (!tested) errors.test = t.errTestFirst;
    }
    if (target !== "later") {
      if (!cryptoOk || !key) errors._ = t.noWebCrypto;
      else if (!downloaded) errors.download = t.errDownloadFirst;
      else if (!stored) errors.stored = t.errConfirmStored;
    }
    return checkThenSave(errors, () => saveBackups({ ...answer(), ...(target === "share" && protocol === "smb" ? { password } : {}) }), t);
  };

  return (
    <Form check={check} onValid={() => onDone(answer())} aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.backupsTitle}</h1>
      <p className="setup-lead">{t.backupsLead}</p>
      <RadioCards
        label={t.backupTarget}
        name="target"
        value={target}
        onChange={(v) => setTarget(v as Target)}
        choices={[
          { value: "usb", title: t.usbDisk, description: t.usbDiskDesc, icon: <HardDrive size={18} /> },
          { value: "share", title: t.networkShare, description: t.networkShareDesc, icon: <FolderSync size={18} /> },
          { value: "later", title: t.later, description: t.laterDesc, icon: <Clock size={18} /> },
        ]}
      />

      {target === "later" ? (
        <div className="setup-block-tight">
          <Notice icon={<TriangleAlert size={16} />} tone="warning" title={t.laterTitle}>{t.laterText}</Notice>
        </div>
      ) : (
        <>
          <div className="setup-detail">
            {target === "usb" && (disks.length ? (
              <SelectField name="disk" label={t.backupDisk} description={t.diskHint} value={disk} onChange={setDisk}
                           options={disks.map((d) => ({ id: d.id, label: `${d.name} · ${diskSize(d.size_bytes, locale)} · ${d.bus}` }))} />
            ) : (
              <div className="setup-no-disk">
                <p className="setup-detail-note" role="status">{t.noDisk}</p>
                <Button size="small" onPress={() => getState().then((s) => {
                  setDisks(s.usb_disks); setDisk(s.usb_disks[0]?.id ?? "");
                })}>{t.lookAgain}</Button>
              </div>
            ))}
            {target === "share" && (
              <>
                <SelectField name="protocol" label={t.shareType} value={protocol} onChange={(v) => setProtocol(v as "smb" | "nfs")}
                             options={[{ id: "smb", label: t.smb }, { id: "nfs", label: t.nfs }]} />
                <TextField name="address" label={t.shareAddress} description={t.shareAddressHint} value={address}
                           onChange={setAddress} autoComplete="off"
                           placeholder={protocol === "smb" ? "\\\\nas.office.local\\backups" : "nas.office.local:/backups"} />
                {protocol === "smb" && (
                  <div className="setup-row2">
                    <TextField name="user" label={t.shareUser} value={user} onChange={setUser} autoComplete="off" placeholder="backup-suveryn" />
                    <PasswordField name="password" label={t.sharePassword} value={password} onChange={setPassword} autoComplete="off" />
                  </div>
                )}
                <TestRow test={test} tested={tested} onTest={runTest} />
              </>
            )}
            <div className="setup-divider" />
            <SelectField name="retention" label={t.keepFor} description={t.keepHint} value={String(retention)}
                         onChange={(v) => setRetention(Number(v) as Retention)}
                         options={RETENTIONS.map((d) => ({ id: String(d), label: t.days(d) }))} />
          </div>

          <h2 className="setup-subtitle setup-section">{t.recoveryHeading}</h2>
          <p className="setup-sublead">{t.recoveryLead}</p>
          <div className="setup-key">
            <span className="ui-fact-icon" aria-hidden><KeyRound size={18} /></span>
            <span className="setup-key-body">
              <span className="setup-key-title">{t.recoveryKey}</span>
              <span className="setup-detail-note">{cryptoOk ? t.recoveryKeyDesc : t.noWebCrypto}</span>
            </span>
            <DownloadButton downloaded={downloaded} disabled={!key} label={t.download} doneLabel={t.downloaded}
                            aria={t.downloadLabel} onPress={download} />
          </div>
          <Checkbox name="stored" checked={stored} onChange={setStored}>{t.recoveryConfirm}</Checkbox>
        </>
      )}
      <StepFooter onBack={onBack} back={t.back} next={t.continue} />
    </Form>
  );
}

function DownloadButton({ downloaded, disabled, label, doneLabel, aria, onPress }: {
  downloaded: boolean; disabled: boolean; label: string; doneLabel: string; aria: string; onPress: () => void;
}) {
  const { error, clear } = useFieldError("download");
  return (
    <span className="setup-key-action" data-field-invalid={error ? true : undefined}>
      <Button size="small" isDisabled={disabled} onPress={() => { clear(); onPress(); }} aria-label={aria}
              aria-describedby={error ? "download-error" : undefined}>
        {downloaded ? <CircleCheck size={14} aria-hidden /> : <Download size={14} aria-hidden />}
        {downloaded ? doneLabel : label}
      </Button>
      {error && <span id="download-error" className="ui-field-error">{error}</span>}
    </span>
  );
}

function TestRow({ test, tested, onTest }: {
  test: { state: string; message?: string }; tested: boolean; onTest: () => void;
}) {
  const t = useText();
  const { error, clear } = useFieldError("test");
  const status = test.state === "testing" ? t.testing : tested ? t.testOk : test.state === "failed" ? test.message : t.notTested;
  return (
    <div className="setup-test">
      <span data-field-invalid={error ? true : undefined}>
        <Button size="small" isDisabled={test.state === "testing"} onPress={() => { clear(); onTest(); }}
                aria-describedby="share-test-status">{t.testConnection}</Button>
      </span>
      <span id="share-test-status" className="setup-test-status" role="status"
            data-state={tested ? "ok" : test.state === "failed" || error ? "failed" : undefined}>
        {error && !tested && test.state !== "failed" ? error : status}
      </span>
    </div>
  );
}
