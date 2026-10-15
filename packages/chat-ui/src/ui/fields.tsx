/**
 * Text fields (suveryn-tracker#44): label, input, optional hint and error, wired together by React
 * Aria (aria-describedby, aria-invalid). Errors come from the screen (shown when it is submitted,
 * never while typing; see Form in forms.tsx), in the interface's language, with an icon: the brand
 * has no error red, so an error is accent-ink plus an icon and a message.
 */
import { CircleAlert, Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { parseDate } from "@internationalized/date";
import type { KeyboardEvent } from "react";
import {
  DateField as AriaDateField,
  DateInput,
  DateSegment,
  FieldError,
  Group,
  Input,
  Label,
  NumberField as AriaNumberField,
  Text,
  TextArea as AriaTextArea,
  TextField as AriaTextField,
  ToggleButton,
  type TextFieldProps as AriaTextFieldProps,
} from "react-aria-components";

export type TextFieldProps = Omit<AriaTextFieldProps, "className" | "children"> & {
  label: string;
  description?: string;
  placeholder?: string;
};

export function TextField({ label, description, placeholder, ...props }: TextFieldProps) {
  return (
    <AriaTextField {...props} className="ui-field">
      <Label className="ui-label">{label}</Label>
      <Input className="ui-input" placeholder={placeholder} />
      {description && <Text slot="description" className="ui-hint">{description}</Text>}
      <Error />
    </AriaTextField>
  );
}

export type PasswordFieldProps = TextFieldProps & {
  /** The show/hide button's name, e.g. "Show password" (it is a toggle: pressed means shown). */
  showLabel?: string;
};

/** A password field. With showLabel it has a show/hide toggle (aria-pressed), which keeps the focus
 *  where it is and doesn't submit the form. */
export function PasswordField({ label, description, placeholder, showLabel, ...props }: PasswordFieldProps) {
  const [shown, setShown] = useState(false);
  return (
    <AriaTextField {...props} type={shown ? "text" : "password"} className="ui-field">
      <Label className="ui-label">{label}</Label>
      <Group className="ui-input-group">
        <Input className="ui-input" placeholder={placeholder} />
        {showLabel && (
          <ToggleButton className="ui-icon-button" aria-label={showLabel} isSelected={shown} onChange={setShown}>
            {shown ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}
          </ToggleButton>
        )}
      </Group>
      {description && <Text slot="description" className="ui-hint">{description}</Text>}
      <Error />
    </AriaTextField>
  );
}

/**
 * A number in the interface's language: "3,5" in Dutch and French, "3.5" in English, typed either way
 * and shown back formatted. The form receives it under `name` as a plain number ("3.5").
 */
export function NumberField({ label, description, name, value, onChange, minValue, maxValue, maxDecimals = 2,
                              className }: {
  label: string; description?: string; name: string; value: number; onChange: (value: number) => void;
  minValue?: number; maxValue?: number; maxDecimals?: number; className?: string;
}) {
  return (
    <AriaNumberField name={name} value={value} onChange={onChange} minValue={minValue} maxValue={maxValue}
                     formatOptions={{ maximumFractionDigits: maxDecimals }} className={className ?? "ui-field"}>
      <Label className="ui-label">{label}</Label>
      <Input className="ui-input" />
      {description && <Text slot="description" className="ui-hint">{description}</Text>}
      <Error />
    </AriaNumberField>
  );
}

/**
 * A date as day, month and year in the order of the interface's language, each typed or changed with
 * the arrow keys. `value` is "YYYY-MM-DD", or "" for none.
 */
export function DateField({ label, value, onChange, minValue, className }: {
  label: string; value: string; onChange: (value: string) => void; minValue?: string; className?: string;
}) {
  return (
    <AriaDateField value={value ? parseDate(value) : null} onChange={(d) => onChange(d ? d.toString() : "")}
                   minValue={minValue ? parseDate(minValue) : undefined} granularity="day"
                   className={className ?? "ui-field"}>
      <Label className="ui-label">{label}</Label>
      <DateInput className="ui-input ui-date-input">
        {(segment) => <DateSegment segment={segment} className="ui-date-segment" />}
      </DateInput>
      <Error />
    </AriaDateField>
  );
}

/** Text over several lines. `hideLabel` keeps the label for screen readers only (the chat's question
 *  box, whose placeholder already says what to type). */
export function TextArea({ label, hideLabel, value, onChange, onKeyDown, placeholder, rows = 1, className }: {
  label: string; hideLabel?: boolean; value: string; onChange: (value: string) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void; placeholder?: string; rows?: number; className?: string;
}) {
  return (
    <AriaTextField value={value} onChange={onChange} className={className}>
      <Label className={hideLabel ? "ui-visually-hidden" : "ui-label"}>{label}</Label>
      <AriaTextArea rows={rows} placeholder={placeholder} onKeyDown={onKeyDown} />
    </AriaTextField>
  );
}

function Error() {
  return (
    <FieldError className="ui-field-error">
      {({ validationErrors }) => (
        <>
          <CircleAlert size={16} aria-hidden />
          <span>{validationErrors.join(" ")}</span>
        </>
      )}
    </FieldError>
  );
}
