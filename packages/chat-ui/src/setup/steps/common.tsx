/**
 * What every setup step shares: turning the appliance's refusals into messages in the interface's
 * language, and the footer with Back and Continue.
 */
import type { ReactNode } from "react";
import { Button, FormError, useFormPending, type FieldErrors } from "../../ui";
import { messageText } from "../../lib/messages";
import { Refused } from "../api";
import type { Text } from "../i18n";

/** The appliance refused or failed: its codes worded, by field (an unplanned failure with its reference); an
 *  appliance that didn't answer at all as one message. */
export function errorsFrom(e: unknown, t: Text): FieldErrors {
  if (e instanceof Refused) {
    return Object.fromEntries(Object.entries(e.fields).map(([field, message]) => [field, messageText(message, t)]));
  }
  return { _: t.errUnexpected };
}

/** Runs `save` when `local` found nothing; returns the errors either way. */
export async function checkThenSave(local: FieldErrors, save: () => Promise<unknown>, t: Text): Promise<FieldErrors> {
  if (Object.keys(local).length) return local;
  try {
    await save();
    return {};
  } catch (e) {
    return errorsFrom(e, t);
  }
}

/** Continue is busy while the appliance checks the step (the form says aria-busy). React Aria's own
 *  isPending isn't used: it announces through elements that point at the button after it is gone
 *  (the next step has replaced it), which axe reports as images without a name. */
export function StepFooter({ onBack, back, next }: { onBack?: () => void; back: string; next: ReactNode }) {
  const pending = useFormPending();
  return (
    <>
      <FormError />
      <div className="setup-footer">
        {onBack ? <Button onPress={onBack}>{back}</Button> : <span />}
        <Button type="submit" variant="primary" data-busy={pending || undefined}>{next}</Button>
      </div>
    </>
  );
}
