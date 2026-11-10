/**
 * Cases (suveryn-tracker#10): opening a new case, closing one (stage 3), and deleting one.
 *
 * A new case asks for the office's own file number, a name, the type and, when the office's default is the
 * whole office, who sees it (board G14; the subject left this dialog, it stays on the case). A taken reference
 * says so under its field, with a link to that case when the person sees it. The hint under the name says
 * what the design decided: no client names on the label; the parties are in the documents. The type is a combo box: the notarial list as suggestions (stored by their id, so the
 * label follows the interface language), or another sector's own word, stored as typed (types are
 * data per appliance, later).
 * Closing is the normal end of a case: it says the case stays readable, that it is deleted after
 * the office's keep period (or kept until deleted by hand), and that it can be reopened.
 * Deleting is for a case opened by mistake: the dialog says the documents and conversations go
 * with it, and the focus starts on Cancel.
 */
import { useEffect, useRef, useState } from "react";
import { createCase, HttpError, type Case, type KeepPeriod, type NewCase } from "../api";
import { useT } from "../i18n";
import { ComboBoxField, Dialog, Form, RadioCards, TextButton, TextField } from "../ui";

const CASE_TYPES = ["sale", "company-formation", "estate", "gift", "marriage-contract", "care-mandate"] as const;

/** The type's label in the interface language; an unknown type (another sector's) is shown as is. */
export function caseTypeLabel(type: string, m: ReturnType<typeof useT>): string {
  const labels: Record<string, string> = {
    "sale": m.caseTypeSale, "company-formation": m.caseTypeCompany, "estate": m.caseTypeEstate, "gift": m.caseTypeGift,
    "marriage-contract": m.caseTypeMarriage, "care-mandate": m.caseTypeCareMandate,
  };
  return labels[type] ?? type;
}

export function NewCaseDialog({ open, officeWide, cases, onCreated, onOpenExisting, onCancel }: {
  open: boolean;
  /** The office's default access is the whole office: the choice offered (with members only, a case can't be opened
   *  to the office, so there is nothing to choose). */
  officeWide: boolean;
  /** The cases the person sees: a taken reference links to its case when it is one of them. */
  cases: Case[];
  onCreated: (c: Case) => void;
  onOpenExisting: (c: Case) => void;
  onCancel: () => void;
}) {
  const m = useT();
  const [reference, setReference] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<string>(caseTypeLabel("sale", m));
  const [access, setAccess] = useState<"default" | "restricted">("default");
  const [taken, setTaken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) { setReference(""); setName(""); setType(caseTypeLabel("sale", m)); setAccess("default"); setTaken(null); setError(null); setBusy(false); }
  }, [open, m]);
  const created = useRef<Case | null>(null);

  // A known type by its id, whatever the language; another sector's word as typed.
  const typeId = CASE_TYPES.find((id) => caseTypeLabel(id, m).toLowerCase() === type.trim().toLowerCase()) ?? type.trim();
  // Checked, then opened, in one step: a taken reference is said under its field (board G14), as a field error.
  const check = async (): Promise<Record<string, string>> => {
    const errors: Record<string, string> = {};
    if (!reference.trim()) errors.reference = m.required;
    if (!name.trim()) errors.name = m.required;
    if (!type.trim()) errors.type = m.required;
    if (Object.keys(errors).length) return errors;
    setBusy(true);
    setError(null);
    setTaken(null);
    const body: NewCase = { reference: reference.trim(), name: name.trim(), type: typeId, subject: {}, access };
    try {
      created.current = await createCase(body);
      return {};
    } catch (e) {
      setBusy(false);
      if (e instanceof HttpError && e.status === 409) {
        const existing = cases.find((c) => c.reference === body.reference);
        setTaken(existing ? existing.id : null);
        return { reference: existing ? m.caseExistsOr(body.reference) : m.caseExists(body.reference) };
      }
      setError(m.createCaseFailed((e as Error).message));
      return { _: "" };
    }
  };
  const existing = taken ? cases.find((c) => c.id === taken) ?? null : null;

  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="form" title={m.newCaseTitle} closeLabel={m.close} error={error}
            primary={{ label: m.createCase, form: "new-case", busyLabel: m.creating }} cancel={{ label: m.cancel }}>
      <p>{m.newCaseIntro}</p>
      <Form id="new-case" check={check} onValid={() => { if (created.current) onCreated(created.current); }} className="case-form">
        <TextField name="reference" label={m.caseReference} description={m.caseReferenceHint} value={reference}
                   onChange={(v) => { setReference(v); setTaken(null); }} autoFocus maxLength={100}
                   errorAction={existing && <><TextButton link onPress={() => onOpenExisting(existing)}>{m.openCaseRef(existing.reference)}</TextButton>.</>} />
        <TextField name="name" label={m.caseName} description={m.caseNameHint} value={name} onChange={setName} maxLength={200} />
        <ComboBoxField name="type" label={m.caseType} description={m.caseTypeHint} value={type} onChange={setType}
                       options={CASE_TYPES.map((id) => ({ id, label: caseTypeLabel(id, m) }))} />
        {officeWide && (
          <div className="case-form-access">
            <span className="ui-label">{m.whoSeesThisCase}</span>
            <RadioCards dotFirst label={m.whoSeesThisCase} name="access" value={access} onChange={(v) => setAccess(v as "default" | "restricted")}
                        choices={[{ value: "default", title: m.accessOffice, description: m.officeDefault },
                                  { value: "restricted", title: m.accessMembers, description: m.membersAfterOpening }]} />
          </div>
        )}
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
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="confirmation" title={m.closeCaseTitle(kase?.reference ?? "")} error={error}
            primary={{ label: m.closeCase, onPress: close, busyLabel: m.closing }} cancel={{ label: m.cancel }}>
      <p>{m.closeCaseBody}</p>
      <p>{kept ? m.closeCaseKept(kept) : m.closeCaseKeptManual}</p>
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
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="confirmation" risky title={m.deleteCaseTitle(kase?.reference ?? "")}
            error={error} primary={{ label: m.deleteCase, onPress: remove, busyLabel: m.deleting }} cancel={{ label: m.cancel }}>
      <p>{m.deleteCaseBody}</p>
    </Dialog>
  );
}
