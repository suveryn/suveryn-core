/**
 * Setup step 3: Certificate (design web-03-certificate*.html). Self-signed (the default), or the
 * office's own: certificate, private key and an optional chain, read in the browser as PEM text and
 * checked by the appliance on Continue (it must cover <name>.local, the key must match, not expired).
 */
import { FileBadge, FileKey, FileText, Info, KeyRound } from "lucide-react";
import { useRef, useState } from "react";
import { Chips, FilePick, Form, Note, RadioCards, readText, type FieldErrors } from "../../ui";
import { saveCertificate, type CertificateAnswer, type SetupState } from "../api";
import { useText } from "../i18n";
import { errorsFrom, StepFooter } from "./common";

type Props = { state: SetupState; onBack: () => void; onDone: (c: CertificateAnswer) => void; headingId: string };

export function Certificate({ state, onBack, onDone, headingId }: Props) {
  const t = useText();
  const [kind, setKind] = useState<"self-signed" | "own">(state.answers.certificate?.kind ?? "self-signed");
  const [cert, setCert] = useState<File | null>(null);
  const [key, setKey] = useState<File | null>(null);
  const [chain, setChain] = useState<File | null>(null);
  const saved = useRef<CertificateAnswer | null>(null);
  const ip = state.address.split("/")[0];

  const check = async (): Promise<FieldErrors> => {
    try {
      if (kind === "self-signed") { saved.current = await saveCertificate({ kind }); return {}; }
      const errors: FieldErrors = {};
      if (!cert) errors.certificate = t.errCertMissing;
      if (!key) errors.key = t.errKeyMissing;
      if (Object.keys(errors).length) return errors;
      const [c, k, ch] = await Promise.all([readText(cert!), readText(key!), chain ? readText(chain) : Promise.resolve(undefined)]);
      if (c === null) errors.certificate = t.errFileTooLarge;
      if (k === null) errors.key = t.errFileTooLarge;
      if (ch === null) errors.chain = t.errFileTooLarge;
      if (Object.keys(errors).length) return errors;
      saved.current = await saveCertificate({ kind, certificate: c!, key: k!, ...(ch ? { chain: ch } : {}) });
      return {};
    } catch (e) {
      return errorsFrom(e, t);
    }
  };

  return (
    <Form check={check} onValid={() => saved.current && onDone(saved.current)} aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.certTitle}</h1>
      <p className="setup-lead">{t.certLead}</p>
      <RadioCards
        label={t.certTitle}
        name="kind"
        value={kind}
        onChange={(v) => setKind(v as typeof kind)}
        choices={[
          { value: "self-signed", title: t.selfSigned, description: t.selfSignedDesc, icon: <KeyRound size={18} /> },
          { value: "own", title: t.ownCert, description: t.ownCertDesc, icon: <FileBadge size={18} /> },
        ]}
      />
      <div className="setup-detail">
        {kind === "self-signed" ? (
          <>
            <p className="ui-eyebrow setup-detail-label">{t.covers}</p>
            <Chips label={t.covers} items={[`${state.name}.local`, ip]} />
            <p className="setup-detail-note">{t.coversHint}</p>
          </>
        ) : (
          <>
            <FilePick name="certificate" title={t.certFile} hint={t.certFileHint} accept={[".crt", ".pem", ".cer"]}
                      file={cert} onChange={setCert} chooseLabel={t.chooseFile} icon={<FileBadge size={16} />} />
            <FilePick name="key" title={t.keyFile} hint={t.keyFileHint} accept={[".key", ".pem"]}
                      file={key} onChange={setKey} chooseLabel={t.chooseFile} icon={<FileKey size={16} />} />
            <FilePick name="chain" title={t.chainFile} hint={t.chainFileHint} accept={[".pem", ".crt"]}
                      file={chain} onChange={setChain} chooseLabel={t.chooseFile} icon={<FileText size={16} />} />
            <Note icon={<Info size={14} />}>{t.mustCover(state.name)}</Note>
          </>
        )}
      </div>
      <StepFooter onBack={onBack} back={t.back} next={t.continue} />
    </Form>
  );
}
