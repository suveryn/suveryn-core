/**
 * Setup step 4: Support agreement (design web-04-support-agreement*.html, suveryn-tracker#35). The
 * appliance's ID and key fingerprint, a QR code with the portal's registration link (drawn as SVG:
 * no image, no app), and the manifest the portal issues, checked on the appliance when it is chosen.
 * Optional: Continue without a manifest skips it.
 */
import { Clock } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button as AriaButton, FileTrigger } from "react-aria-components";
import { CopyButton, FileDrop, Form, Notice, QrCode, Rows, type FieldErrors } from "../../ui";
import { checkManifest, skipManifest, type Manifest, type SetupState } from "../api";
import { LOCALES, useLang, useText, type Text } from "../text";
import { checkThenSave, errorsFrom, StepFooter } from "./common";

/** The portal's registration page (placeholder until the portal exists; the console's C8 uses the same). */
export const PORTAL_REGISTER = "https://portal.suveryn.com/r";
export const registrationUrl = (id: string, fingerprint: string) => `${PORTAL_REGISTER}/${id}?k=${fingerprint.slice(0, 16)}`;

/** "SHA256:" and the hex fingerprint in groups of four, as the console shows it. */
export const groupedFingerprint = (fp: string) => `SHA256:${fp.match(/.{1,4}/g)!.join(" ")}`;

type Props = { state: SetupState; onBack: () => void; onDone: (m: Manifest | null) => void; headingId: string };

export function Support({ state, onBack, onDone, headingId }: Props) {
  const t = useText();
  const lang = useLang();
  const [manifest, setManifest] = useState<Manifest | null>(state.answers.support ?? null);
  const [uploadError, setUploadError] = useState<FieldErrors>({});
  const [copyFailed, setCopyFailed] = useState(false);
  const id = state.appliance;

  const upload = async (file: File) => {
    setUploadError({});
    try { setManifest(await checkManifest(file)); } catch (e) { setUploadError(errorsFrom(e, t)); }
  };

  return (
    <Form check={() => (manifest ? {} : checkThenSave({}, skipManifest, t))} onValid={() => onDone(manifest)}
          aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.supportTitle}</h1>
      <p className="setup-lead">{t.supportLead}</p>

      {manifest ? (
        <ManifestRows manifest={manifest} t={t} locale={LOCALES[lang]} onReplace={upload} error={uploadError._} />
      ) : (
        <>
          <h2 className="setup-subtitle setup-numbered">{t.registerHeading}</h2>
          {id ? (
            <div className="setup-register">
              <div className="setup-register-ids">
                <p className="ui-eyebrow">{t.applianceId}</p>
                <p className="setup-mono">{id.id}</p>
                <p className="ui-eyebrow">{t.keyFingerprint}</p>
                <p className="setup-mono">{groupedFingerprint(id.fingerprint)}</p>
                <CopyButton text={`${id.id}\n${groupedFingerprint(id.fingerprint)}`} label={t.copyBoth} copiedLabel={t.copied}
                            onFail={() => setCopyFailed(true)} />
                {copyFailed && <p className="setup-detail-note" role="status">{t.copyFailed}</p>}
              </div>
              <figure className="setup-qr">
                <QrCode text={registrationUrl(id.id, id.fingerprint)} label={t.qrLabel} />
                <figcaption>{t.qrCaption}</figcaption>
              </figure>
            </div>
          ) : (
            <Notice icon={<Clock size={16} />} tone="warning">{t.identityMissing}</Notice>
          )}
          <ol className="setup-how">
            <li><b>{t.howScan}</b> {t.howScanMore}</li>
            <li>{t.howPaste}</li>
            <li>{t.howPartner}</li>
          </ol>

          <h2 className="setup-subtitle setup-numbered">{t.uploadHeading}</h2>
          <UploadErrors errors={uploadError}>
            <FileDrop name="manifest" accept={[".yaml", ".yml"]} dropLabel={t.dropManifest} chooseLabel={t.chooseAFile}
                      hints={[t.manifestHint, t.manifestChecked]} onFile={upload} />
          </UploadErrors>
          <Notice icon={<Clock size={16} />}>{t.skipNote}</Notice>
        </>
      )}
      <StepFooter onBack={onBack} back={t.back} next={t.continue} />
    </Form>
  );
}

/** Shows an upload's error under the drop area: the upload happens on choosing, not on Continue. */
function UploadErrors({ errors, children }: { errors: FieldErrors; children: ReactNode }) {
  return (
    <div className="setup-block-tight">
      {children}
      {errors._ && <p className="ui-form-error" role="alert">{errors._}</p>}
    </div>
  );
}

function ManifestRows({ manifest: m, t, locale, onReplace, error }: {
  manifest: Manifest; t: Text; locale: string; onReplace: (f: File) => void; error?: string;
}) {
  const date = (iso: string) => new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" }).format(new Date(iso));
  const shortId = `${m.appliance_id.slice(0, 8)}…${m.appliance_id.slice(-12)}`;
  return (
    <div className="setup-stack">
      <Rows rows={[
        { label: t.agreement, value: m.edition, tone: "ok", detail: t.validFor(shortId) },
        { label: t.users, value: String(m.users), detail: t.usersDetail },
        { label: t.validUntil, value: date(m.valid_until), detail: t.remindedBefore },
        { label: t.nextCheckIn, value: date(m.next_check_in), detail: t.checkInDetail },
        { label: t.certified, value: t.certifiedValue(m.connectors, m.playbooks), detail: t.certifiedDetail },
      ]} />
      <ReplaceButton label={t.replaceManifest} onFile={onReplace} />
      {error && <p className="ui-form-error" role="alert">{error}</p>}
    </div>
  );
}

function ReplaceButton({ label, onFile }: { label: string; onFile: (f: File) => void }) {
  return (
    <FileTrigger acceptedFileTypes={[".yaml", ".yml"]} onSelect={(f) => { const file = f?.[0]; if (file) onFile(file); }}>
      <AriaButton className="ui-link-button setup-replace">{label}</AriaButton>
    </FileTrigger>
  );
}
