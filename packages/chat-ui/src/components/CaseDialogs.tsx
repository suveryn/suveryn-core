/**
 * Cases (suveryn-tracker#10): opening a new case, closing one (stage 3), and deleting one.
 *
 * A new case asks for the office's own file number, a name, the type and a short subject. The hint
 * under the name says what the design decided: no client names on the label; the parties are in the
 * documents. The type is a combo box: the notarial list as suggestions (stored by their id, so the
 * label follows the interface language), or another sector's own word, stored as typed (types are
 * data per appliance, later).
 * Closing is the normal end of a case: it says the case stays readable, that it is deleted after
 * the office's keep period (or kept until deleted by hand), and that it can be reopened.
 * Deleting is for a case opened by mistake: the dialog says the documents and conversations go
 * with it, and keeping it is the focused choice.
 */
import { AlertCircle, FolderPlus, Lock, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { createCase, type Case, type KeepPeriod, type NewCase } from "../api";
import { useT } from "../i18n";
import { Button, ComboBoxField, Dialog, Form, InlineNotice, TextButton, TextField } from "../ui";

export const CASE_TYPES = ["sale", "company-formation", "estate", "gift", "marriage-contract"] as const;

/** The type's label in the interface language; an unknown type (another sector's) is shown as is. */
export function caseTypeLabel(type: string, m: ReturnType<typeof useT>): string {
  const labels: Record<string, string> = {
    "sale": m.caseTypeSale, "company-formation": m.caseTypeCompany, "estate": m.caseTypeEstate, "gift": m.caseTypeGift,
    "marriage-contract": m.caseTypeMarriage,
  };
  return labels[type] ?? type;
}

export function NewCaseDialog({ open, onCreated, onCancel }: { open: boolean; onCreated: (c: Case) => void; onCancel: () => void }) {
  const m = useT();
  const [reference, setReference] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<string>(caseTypeLabel("sale", m));
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setReference(""); setName(""); setType(caseTypeLabel("sale", m)); setSubject(""); setError(null); setBusy(false); } }, [open, m]);

  const check = () => {
    const errors: Record<string, string> = {};
    if (!reference.trim()) errors.reference = m.required;
    if (!name.trim()) errors.name = m.required;
    if (!type.trim()) errors.type = m.required;
    return errors;
  };
  // A known type by its id, whatever the language; another sector's word as typed.
  const typeId = CASE_TYPES.find((id) => caseTypeLabel(id, m).toLowerCase() === type.trim().toLowerCase()) ?? type.trim();
  const create = async () => {
    setBusy(true);
    setError(null);
    const body: NewCase = { reference: reference.trim(), name: name.trim(), type: typeId,
                            subject: subject.trim() ? { description: subject.trim() } : {} };
    try {
      onCreated(await createCase(body));
    } catch (e) {
      setError(m.createCaseFailed((e as Error).message));
      setBusy(false);
    }
  };

  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} title={m.newCaseTitle} actions={<>
      <Button variant="primary" type="submit" form="new-case" isDisabled={busy}>
        <FolderPlus size={16} aria-hidden /> {busy ? m.creating : m.createCase}
      </Button>
      <TextButton onPress={onCancel} isDisabled={busy}>{m.cancel}</TextButton>
    </>}>
      <Form id="new-case" check={check} onValid={create} className="case-form">
        <TextField name="reference" label={m.caseReference} description={m.caseReferenceHint} value={reference}
                   onChange={setReference} autoFocus maxLength={100} />
        <TextField name="name" label={m.caseName} description={m.caseNameHint} value={name} onChange={setName} maxLength={200} />
        <ComboBoxField name="type" label={m.caseType} description={m.caseTypeHint} value={type} onChange={setType}
                       options={CASE_TYPES.map((id) => ({ id, label: caseTypeLabel(id, m) }))} />
        <TextField name="subject" label={m.caseSubject} description={m.caseSubjectHint} value={subject} onChange={setSubject} maxLength={500} />
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      </Form>
    </Dialog>
  );
}

/** The office's keep period in words, for the close dialog; null when a closed case is kept until deleted by hand. */
export function keepPeriodLabel(period: KeepPeriod | undefined, m: ReturnType<typeof useT>): string | null {
  return period === "6m" ? m.keepSixMonths : period === "1y" ? m.keepOneYear : period === "5y" ? m.keepFiveYears : null;
}

export function CloseCaseDialog({ open, kase, period, onCloseCase, onCancel }: {
  open: boolean; kase: Case | null; period: KeepPeriod | undefined; onCloseCase: () => Promise<void>; onCancel: () => void;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setBusy(false); } }, [open]);
  const close = async () => {
    setBusy(true);
    setError(null);
    try {
      await onCloseCase();
    } catch (e) {
      setError(m.closeCaseFailed((e as Error).message));
      setBusy(false);
    }
  };
  const kept = keepPeriodLabel(period, m);
  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} title={m.closeCaseTitle(kase?.reference ?? "")} actions={<>
      <TextButton onPress={onCancel} isDisabled={busy}>{m.cancel}</TextButton>
      <Button variant="primary" autoFocus onPress={close} isDisabled={busy}><Lock size={16} aria-hidden /> {busy ? m.closing : m.closeCase}</Button>
    </>}>
      <p>{m.closeCaseBody}</p>
      <p>{kept ? m.closeCaseKept(kept) : m.closeCaseKeptManual}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}

export function DeleteCaseDialog({ open, kase, onDelete, onCancel }: {
  open: boolean; kase: Case | null; onDelete: () => Promise<void>; onCancel: () => void;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setBusy(false); } }, [open]);
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await onDelete();
    } catch (e) {
      setError(m.deleteCaseFailed((e as Error).message));
      setBusy(false);
    }
  };
  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} title={m.deleteCaseTitle(kase?.reference ?? "")} actions={<>
      {/* Keep first: the dialog focuses it */}
      <Button variant="primary" autoFocus onPress={onCancel} isDisabled={busy}>{m.keep}</Button>
      <Button onPress={remove} isDisabled={busy}><Trash2 size={16} aria-hidden /> {busy ? m.deleting : m.deleteCase}</Button>
    </>}>
      <p>{m.deleteCaseBody}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
