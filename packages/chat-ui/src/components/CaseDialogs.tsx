/**
 * Cases (suveryn-tracker#10): opening a new case, closing one (stage 3), and deleting one.
 *
 * A new case asks for the office's own file number, a name, the type and, when the office's default is the
 * whole office, who sees it (board G14). A taken reference
 * says so under its field, with a link to that case when the person sees it. The hint under the name says
 * what the design decided: no client names on the label; the parties are in the documents. The type is chosen from
 * the server's list (suveryn-tracker#229: core's reference content and the installed packs), stored by its id, so
 * its word follows the interface language; the case's manager can change it later (board 14).
 * Closing is the normal end of a case: it says the case stays readable, that it is deleted after
 * the office's keep period (or kept until deleted by hand), and that it can be reopened.
 * Deleting is for a case opened by mistake: the dialog says the documents and conversations go
 * with it, and the focus starts on Cancel.
 */
import { useEffect, useRef, useState } from "react";
import { createCase, HttpError, type Case, type KeepPeriod, type NewCase } from "../api";
import { useT } from "../i18n";
import { caseTypeLabel, loadCaseTypes, useCaseTypes, useCaseTypesFailure } from "../lib/caseTypes";
import { Dialog, Form, RadioCards, SelectField, TextButton, TextField } from "../ui";

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
  const types = useCaseTypes();
  const typesFailure = useCaseTypesFailure();
  const [reference, setReference] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<string>("");
  const [access, setAccess] = useState<"default" | "restricted">("default");
  const [taken, setTaken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) { setReference(""); setName(""); setType(""); setAccess("default"); setTaken(null); setError(null); setBusy(false); }
    if (open && !types.length) void loadCaseTypes();  // a list that couldn't be read is asked for again
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps -- on opening
  const created = useRef<Case | null>(null);

  // The type chosen, else the list's first (the server's order: core's reference content first)
  const typeId = type || types[0]?.id || "";
  // Checked, then opened, in one step: a taken reference is said under its field (board G14), as a field error.
  const check = async (): Promise<Record<string, string>> => {
    const errors: Record<string, string> = {};
    if (!reference.trim()) errors.reference = m.required;
    if (!name.trim()) errors.name = m.required;
    if (!typeId) errors.type = typesFailure ?? m.required;
    if (Object.keys(errors).length) return errors;
    setBusy(true);
    setError(null);
    setTaken(null);
    const body: NewCase = { reference: reference.trim(), name: name.trim(), type: typeId, access };
    try {
      created.current = await createCase(body);
      return {};
    } catch (e) {
      setBusy(false);
      if (e instanceof HttpError && e.status === 409) {
        const existing = cases.find((c) => c.reference === body.reference);
        setTaken(existing ? existing.id : null);
        return { reference: existing ? m.caseExistsOr({ ref: body.reference }) : m.caseExists({ ref: body.reference }) };
      }
      setError(m.createCaseFailed({ why: (e as Error).message }));
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
                   errorAction={existing && <><TextButton link onPress={() => onOpenExisting(existing)}>{m.openCaseRef({ ref: existing.reference })}</TextButton>.</>} />
        <TextField name="name" label={m.caseName} description={m.caseNameHint} value={name} onChange={setName} maxLength={200} />
        <SelectField name="type" label={m.caseType} description={m.caseTypeHint} value={typeId} onChange={setType}
                     placeholder={typesFailure ?? m.loading} options={types.map((t) => ({ id: t.id, label: caseTypeLabel(t.id, types) }))} />
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
      setError(m.closeCaseFailed({ why: (e as Error).message }));
      setBusy(false);
    }
  };
  const kept = keepPeriodLabel(period, m);
  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="confirmation" title={m.closeCaseTitle({ reference: kase?.reference ?? "" })} error={error}
            primary={{ label: m.closeCase, onPress: close, busyLabel: m.closing }} cancel={{ label: m.cancel }}>
      <p>{m.closeCaseBody}</p>
      <p>{kept ? m.closeCaseKept({ period: period === "6m" ? "six_months" : period === "1y" ? "one_year" : "five_years" }) : m.closeCaseKeptManual}</p>
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
      setError(m.deleteCaseFailed({ why: (e as Error).message }));
      setBusy(false);
    }
  };
  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="confirmation" risky title={m.deleteCaseTitle({ reference: kase?.reference ?? "" })}
            error={error} primary={{ label: m.deleteCase, onPress: remove, busyLabel: m.deleting }} cancel={{ label: m.cancel }}>
      <p>{m.deleteCaseBody}</p>
    </Dialog>
  );
}
