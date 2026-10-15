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
import { startTransition, useActionState, useEffect, useRef, type ReactNode } from "react";
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

export function Form({ check, onValid, className, children, ...rest }: Props) {
  const ref = useRef<HTMLFormElement>(null);
  const [errors, submit] = useActionState(async (_: FieldErrors, data: FormData) => {
    const found = await check(data);
    if (Object.keys(found).length === 0) onValid(data);
    return found;
  }, {});

  useEffect(() => {
    if (Object.keys(errors).length === 0) return;
    ref.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
  }, [errors]);

  return (
    <AriaForm ref={ref} validationBehavior="aria" validationErrors={errors} className={className} {...rest}
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                startTransition(() => submit(data));
              }}>
      {children}
    </AriaForm>
  );
}
