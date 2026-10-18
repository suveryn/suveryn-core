/**
 * Setup step 6: Review (design web-06-review.html). Every answer with an Edit link back to its step
 * (which then returns here), the name from the console (changed there), and Start provisioning.
 */
import { Lock, SquareTerminal } from "lucide-react";
import { Form, Notice, Rows, TextButton, type FieldErrors, type Row } from "../../ui";
import type { SetupState } from "../api";
import { LOCALES, useLang, useText } from "../text";
import { StepFooter } from "./common";

export type Editable = 1 | 2 | 3 | 4 | 5;

type Props = { state: SetupState; onBack: () => void; onEdit: (step: Editable) => void; onStart: () => void; headingId: string };

export function Review({ state, onBack, onEdit, onStart, headingId }: Props) {
  const t = useText();
  const locale = LOCALES[useLang()];
  const a = state.answers;
  const ip = state.address.split("/")[0];
  const date = (iso: string) => new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" }).format(new Date(iso));
  const edit = (step: Editable, what: string) => (
    <TextButton link aria-label={t.editLabel(what)} onPress={() => onEdit(step)}>{t.edit}</TextButton>
  );
  const missing = { value: t.notAnswered };

  const rows: Row[] = [
    { label: t.rName, value: state.name, detail: `${state.name}.local · ${ip}`,
      action: <span className="setup-console-hint" title={t.rConsoleLabel}><SquareTerminal size={14} aria-hidden />
                <span aria-hidden>{t.rConsole}</span><span className="ui-visually-hidden">{t.rConsoleLabel}</span></span> },
    { label: t.rInternet, action: edit(1, t.rInternet),
      ...(a.network ? a.network.mode === "air-gapped" ? { value: t.airGapped, detail: t.airGappedChecked }
        : { value: t.connected, detail: a.network.outgoing === "all" ? t.allChecked : t.approvedChecked } : missing) },
    { label: t.rAdmin, action: edit(2, t.rAdmin),
      ...(a.administrator ? { value: a.administrator.name, detail: a.administrator.email } : missing) },
    { label: t.rCert, action: edit(3, t.rCert),
      ...(a.certificate ? a.certificate.kind === "self-signed"
        ? { value: t.selfSignedShort, detail: a.certificate.names.join(", ") }
        : { value: t.ownCertShort, detail: `${a.certificate.names.join(", ")} · ${t.validUntilDate(date(a.certificate.not_after))}` }
        : missing) },
    { label: t.rSupport, action: edit(4, t.rSupport),
      ...(a.support === undefined ? missing : a.support ? { value: a.support.edition, tone: "ok" as const,
            detail: `${t.validUntil} ${date(a.support.valid_until)}` }
        : { value: t.noManifest, detail: t.noManifestDetail }) },
    { label: t.rBackups, action: edit(5, t.rBackups),
      ...(a.backups ? a.backups.target === "later" ? { value: t.laterShort, detail: t.laterDetail }
        : { value: a.backups.target === "usb" ? t.usbDisk : t.networkShare, detail: t.backupsKept(a.backups.retention_days) }
        : missing) },
  ];
  const complete = !!(a.network && a.administrator && a.certificate && a.support !== undefined && a.backups);

  return (
    <Form check={(): FieldErrors => (complete ? {} : { _: t.errNotAnswered })} onValid={onStart} aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.reviewTitle}</h1>
      <p className="setup-lead">{t.reviewLead}</p>
      <div className="setup-stack">
        <Rows rows={rows} />
        <Notice icon={<Lock size={16} />} title={t.closesTitle}>{t.closesText}</Notice>
      </div>
      <StepFooter onBack={onBack} back={t.back} next={t.startProvisioning} />
    </Form>
  );
}
