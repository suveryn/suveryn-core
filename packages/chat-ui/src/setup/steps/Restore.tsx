/**
 * Restoring the office's backup on a replacement appliance (suveryn-tracker#56), instead of setting up
 * afresh. Four screens:
 *
 *  - Source: where the backups are (the USB disk or the share) and the recovery key file setup made.
 *  - Confirm: the appliance looks for the newest backup there and checks it with the key; the screen
 *    shows when it was made and by which appliance, and asks before anything is replaced.
 *  - Progress: the restore's steps, polled every second.
 *  - Done: where the restored appliance answers. It takes the old appliance's name, and its own
 *    accounts and settings: setup is closed and nobody signs in with anything made here.
 *
 * The key and a share's password pass through the page once; the appliance keeps them on its encrypted
 * data partition until the restore has run, then deletes them.
 */
import { ArchiveRestore, Check, CircleAlert, FileKey, FolderSync, HardDrive, Info, LoaderCircle, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button, Facts, FilePick, Form, InlineNotice, LinkButton, Notice, PasswordField, Progress, RadioCards, readText, SelectField,
         StatusList, TextField, type FieldErrors, type StatusItem } from "../../ui";
import { getRestore, getState, saveRestore, startRestore, type RestoreProgress, type SetupState, type UsbDisk } from "../api";
import { LOCALES, useLang, useText, type Text } from "../i18n";
import { checkThenSave, StepFooter } from "./common";
import { diskSize } from "./Backups";

/** "23 October 2026 at 02:30" in the interface's language. */
export function madeAt(iso: string, locale: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(locale, { dateStyle: "long", timeStyle: "short" });
}

/** Polls the restore every second while `active` says so; a failed request is asked again. */
function usePolledRestore(initial: RestoreProgress | null, active: (r: RestoreProgress | null) => boolean) {
  const [restore, setRestore] = useState(initial);
  const [misses, setMisses] = useState(0);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    let last = initial;
    const poll = async () => {
      try {
        last = await getRestore();
        if (stop) return;
        setRestore(last);
        setMisses(0);
      } catch {
        if (!stop) setMisses((m) => m + 1);  // the services restart, or the page's address went with the old name
      }
      if (!stop && active(last)) timer = setTimeout(poll, 1000);
    };
    if (active(initial)) timer = setTimeout(poll, 1000);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { restore, misses };
}

type SourceProps = { state: SetupState; onBack: () => void; onChecking: (r: RestoreProgress) => void; headingId: string };

export function RestoreSource({ state, onBack, onChecking, headingId }: SourceProps) {
  const t = useText();
  const locale = LOCALES[useLang()];
  const [target, setTarget] = useState<"usb" | "share">("usb");
  const [disks, setDisks] = useState<UsbDisk[]>(state.usb_disks);
  const [disk, setDisk] = useState(state.usb_disks[0]?.id ?? "");
  const [protocol, setProtocol] = useState<"smb" | "nfs">("smb");
  const [address, setAddress] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const result = useRef<RestoreProgress | null>(null);  // read by onValid in the same render, so not state
  const failed = state.restore?.state === "failed" ? state.restore.error : undefined;

  const check = async (): Promise<FieldErrors> => {
    const errors: FieldErrors = {};
    if (target === "usb" && !disk) errors._ = t.noDisk;
    if (target === "share") {
      if (!address.trim()) errors.address = t.errShareAddressMissing;
      else if (protocol === "smb" && !user.trim()) errors.user = t.errShareUserMissing;
    }
    if (!keyFile) errors.key = t.errKeyFileMissing;
    if (Object.keys(errors).length) return errors;
    const key = await readText(keyFile!);
    if (key === null) return { key: t.errors.key_invalid };
    return checkThenSave({}, async () => {
      result.current = (await saveRestore(target === "usb" ? { target, disk, key }
        : { target, protocol, address: address.trim(), ...(protocol === "smb" ? { user: user.trim(), password } : {}), key }));
    }, t);
  };

  return (
    <Form check={check} onValid={() => result.current && onChecking(result.current)} aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.restoreTitle}</h1>
      <p className="setup-lead">{t.restoreLead}</p>
      {failed && (
        <div className="setup-block-tight" role="alert">
          <Notice icon={<TriangleAlert size={16} />} tone="warning" title={t.restoreCheckFailed}>
            {t.restoreErrors[failed] ?? t.errUnexpected}
          </Notice>
        </div>
      )}
      <RadioCards
        label={t.restoreWhere}
        name="target"
        value={target}
        onChange={(v) => setTarget(v as "usb" | "share")}
        choices={[
          { value: "usb", title: t.usbDisk, description: t.restoreUsbDesc, icon: <HardDrive size={18} /> },
          { value: "share", title: t.networkShare, description: t.restoreShareDesc, icon: <FolderSync size={18} /> },
        ]}
      />
      <div className="setup-detail">
        {target === "usb" && (disks.length ? (
          <SelectField name="disk" label={t.backupDisk} description={t.restoreDiskHint} value={disk} onChange={setDisk}
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
            <TextField name="address" label={t.shareAddress} value={address} onChange={setAddress} autoComplete="off"
                       placeholder={protocol === "smb" ? "\\\\nas.office.local\\backups" : "nas.office.local:/backups"} />
            {protocol === "smb" && (
              <div className="setup-row2">
                <TextField name="user" label={t.shareUser} value={user} onChange={setUser} autoComplete="off" placeholder="backup-suveryn" />
                <PasswordField name="password" label={t.sharePassword} value={password} onChange={setPassword} autoComplete="off" />
              </div>
            )}
          </>
        )}
        <div className="setup-divider" />
        <FilePick name="key" title={t.recoveryKey} hint={t.restoreKeyHint} accept={[".txt", ".key"]}
                  file={keyFile} onChange={setKeyFile} chooseLabel={t.chooseFile} icon={<FileKey size={16} />} />
      </div>
      <StepFooter onBack={onBack} back={t.back} next={t.restoreFind} />
    </Form>
  );
}

type ConfirmProps = { state: SetupState; initial: RestoreProgress; onBack: (failed: RestoreProgress | null) => void;
                      onStart: (r: RestoreProgress) => void; headingId: string };

export function RestoreConfirm({ state, initial, onBack, onStart, headingId }: ConfirmProps) {
  const t = useText();
  const locale = LOCALES[useLang()];
  const { restore } = usePolledRestore(initial, (r) => r?.state === "checking");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A check that failed goes back to the first screen, which says why.
  useEffect(() => { if (restore?.state === "failed") onBack(restore); });

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      onStart(await startRestore());
    } catch {
      setError(t.errUnexpected);
      setStarting(false);
    }
  };

  if (!restore || restore.state === "checking" || !restore.backup) {
    return (
      <div className="setup-final">
        <span className="setup-final-icon" aria-hidden><LoaderCircle size={22} className="ui-spin" /></span>
        <h1 id={headingId} className="setup-title setup-centred">{t.restoreChecking}</h1>
        <p className="setup-lead setup-centred" aria-busy="true">{t.restoreCheckingLead}</p>
      </div>
    );
  }
  const b = restore.backup;
  return (
    <div>
      <h1 id={headingId} className="setup-title">{t.restoreConfirmTitle}</h1>
      <p className="setup-lead">{t.restoreConfirmLead}</p>
      <Facts facts={[
        { icon: <ArchiveRestore size={18} />, label: t.restoreMade, value: madeAt(b.created, locale) },
        { icon: <HardDrive size={18} />, label: t.restoreFrom, value: `${b.appliance}.local`,
          detail: b.appliance === state.name ? undefined : t.restoreRenamed(state.name, b.appliance) },
      ]} />
      <div className="setup-stack setup-section">
        <Notice icon={<TriangleAlert size={16} />} tone="warning" title={t.restoreReplacesTitle}>{t.restoreReplacesText}</Notice>
        {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      </div>
      <div className="setup-footer">
        <Button onPress={() => onBack(null)} isDisabled={starting}>{t.back}</Button>
        <Button variant="primary" onPress={start} data-busy={starting || undefined}>{t.restoreStart}</Button>
      </div>
    </div>
  );
}

function restoreItems(r: RestoreProgress, t: Text): StatusItem[] {
  return (r.steps ?? []).map((s) => ({ id: s.id, label: t.restoreStepLabel[s.id], state: s.state, stateText: t.stateText[s.state] }));
}

type ProgressProps = { initial: RestoreProgress; onDone: (r: RestoreProgress) => void; onAgain: () => void; headingId: string };

export function RestoreRunning({ initial, onDone, onAgain, headingId }: ProgressProps) {
  const t = useText();
  const { restore, misses } = usePolledRestore(initial, (r) => !r || r.state === "restoring");
  const r = restore ?? initial;
  useEffect(() => { if (r.state === "done") onDone(r); });

  const steps = r.steps ?? [];
  const done = steps.filter((s) => s.state === "done").length;
  const running = steps.find((s) => s.state === "running");
  const failed = r.state === "failed";
  // Near the end the appliance takes the old name and its site: this page's address may stop answering.
  const late = running?.id === "network" || running?.id === "services";

  return (
    <div className="setup-final">
      <span className="setup-final-icon" aria-hidden>{failed ? <CircleAlert size={22} /> : <LoaderCircle size={22} className="ui-spin" />}</span>
      <h1 id={headingId} className="setup-title setup-centred">{t.restoringTitle}</h1>
      <p className="setup-lead setup-centred">{t.restoringLead}</p>
      <div className="setup-stack">
        <div className="setup-progress">
          <Progress value={steps.length ? (done / steps.length) * 100 : 0} label={t.restoringTitle}
                    valueText={t.provDone(done, steps.length || 5)} />
          <p className="setup-detail-note" aria-live="polite">{running ? t.restoreStepNow[running.id] : ""}</p>
        </div>
        <StatusList items={restoreItems(r, t)} />
        {failed ? (
          <>
            <div role="alert">
              <Notice icon={<TriangleAlert size={16} />} tone="warning" title={t.restoreFailedTitle}>{t.restoreFailedText}</Notice>
            </div>
            <Button variant="primary" className="setup-wide" onPress={onAgain}>{t.tryAgain}</Button>
          </>
        ) : misses >= 5 && late && r.address ? (
          <div role="status">
            <Notice icon={<Info size={16} />} title={t.restoreMovedTitle}>{t.restoreMovedText(r.address)}</Notice>
            <LinkButton href={r.address} className="setup-wide">{t.restoreOpen(r.address)}</LinkButton>
          </div>
        ) : (
          <Notice icon={<Info size={16} />}><b className="setup-strong">{t.doNotTurnOff}</b> {t.doNotTurnOffMore}</Notice>
        )}
      </div>
    </div>
  );
}

export function RestoreDone({ restore, headingId }: { restore: RestoreProgress; headingId: string }) {
  const t = useText();
  const url = restore.address ?? "";
  return (
    <div className="setup-final">
      <span className="setup-final-icon" data-tone="ok" aria-hidden><Check size={22} /></span>
      <h1 id={headingId} className="setup-title setup-centred">{t.restoreDoneTitle}</h1>
      <p className="setup-lead setup-centred">{t.restoreDoneLead}</p>
      <div className="setup-stack">
        <StatusList items={restoreItems(restore, t)} />
        <div className="setup-signin">
          <p className="ui-eyebrow">{t.signInAt}</p>
          <p className="setup-signin-url">{url}</p>
        </div>
        <Notice icon={<Info size={16} />} title={t.restoreSupportTitle}>{t.restoreSupportText}</Notice>
        <LinkButton href={url} className="setup-wide">{t.openSuveryn}</LinkButton>
      </div>
    </div>
  );
}
