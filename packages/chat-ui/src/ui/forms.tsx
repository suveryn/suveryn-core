/**
 * A form whose errors appear when it is submitted (Continue), never while typing (suveryn-tracker#44,
 * the setup design: "errors only on Continue"). It uses React 19's form actions: the action checks
 * the fields and returns the errors by field name, which React Aria shows under each field (and
 * clears from a field once it is changed and left). The focus then moves to the first field in error,
 * so keyboard and screen-reader users land on it.
 *
 * The action is started from onSubmit rather than passed as the form's `action`: given `action`, React
 * resets the form after each submission, and React Aria's fields follow a form reset, so every answer
 * would be wiped whenever Continue found an error.
 */
import { createContext, startTransition, useActionState, useContext, useEffect, useMemo, useRef, useState,
         type ReactNode } from "react";
import { Form as AriaForm } from "react-aria-components";

/** Errors by field name; empty when everything is right. */
export type FieldErrors = Record<string, string>;

type Props = {
  /** Checks the fields; returns their errors (or none). May be async (a call to the appliance). */
  check: (data: FormData) => FieldErrors | Promise<FieldErrors>;
  /** Called once the fields are right. */
  onValid: (data: FormData) => void;
  className?: string;
  /** An accessible name, when the screen's heading doesn't name the form. */
  "aria-labelledby"?: string;
  children: ReactNode;
};

/**
 * The errors of the form a field is in, for fields that aren't React Aria text fields (a checkbox, a
 * file): `error` is the field's message, `clear` drops it once the field is changed, and `pending` is
 * true while the form is being checked (a call to the appliance).
 */
type FormErrorsValue = { errors: FieldErrors; clear: (name: string) => void; pending: boolean };
const FormErrorsContext = createContext<FormErrorsValue>({ errors: {}, clear: () => {}, pending: false });
export function useFieldError(name: string): { error: string | undefined; clear: () => void } {
  const { errors, clear } = useContext(FormErrorsContext);
  return { error: errors[name], clear: () => clear(name) };
}
/** True while the form's check runs (e.g. to show Continue as busy). */
export const useFormPending = () => useContext(FormErrorsContext).pending;

export function Form({ check, onValid, className, children, ...rest }: Props) {
  const ref = useRef<HTMLFormElement>(null);
  const [errors, submit, pending] = useActionState(async (_: FieldErrors, data: FormData) => {
    const found = await check(data);
    if (Object.keys(found).length === 0) onValid(data);
    return found;
  }, {});
  const [cleared, setCleared] = useState<{ from: FieldErrors; names: string[] }>({ from: errors, names: [] });
  const shown = useMemo(() => {
    const names = cleared.from === errors ? cleared.names : [];
    return Object.fromEntries(Object.entries(errors).filter(([k]) => !names.includes(k)));
  }, [errors, cleared]);
  const value = useMemo<FormErrorsValue>(() => ({
    errors: shown, pending,
    clear: (name) => setCleared((c) => ({ from: errors, names: [...(c.from === errors ? c.names : []), name] })),
  }), [shown, pending, errors]);

  useEffect(() => {
    if (Object.keys(errors).length === 0) return;
    // The first field in error, in page order: an input React Aria marks invalid, the button of a field
    // marked data-field-invalid (a file, a download: buttons can't be aria-invalid), or the form's own
    // message (an error for the whole step, under `_`).
    const first = ref.current?.querySelector<HTMLElement>(
      "[aria-invalid='true'], [data-field-invalid] button, [data-field-invalid] input, [data-form-error]");
    if (first) { if (!first.matches("input, button, select, textarea, [tabindex]")) first.tabIndex = -1; first.focus(); }
  }, [errors]);

  return (
    <FormErrorsContext.Provider value={value}>
      <AriaForm ref={ref} validationBehavior="aria" validationErrors={shown} className={className} {...rest}
                aria-busy={pending || undefined}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (pending) return;
                  const data = new FormData(e.currentTarget);
                  startTransition(() => submit(data));
                }}>
        {children}
      </AriaForm>
    </FormErrorsContext.Provider>
  );
}

/** An error for the whole form (field `_`), e.g. the appliance refused the step; read when it appears. */
export function FormError() {
  const { error } = useFieldError("_");
  if (!error) return null;
  return <p className="ui-form-error" role="alert" data-form-error>{error}</p>;
}
