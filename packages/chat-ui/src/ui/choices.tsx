/**
 * Choosing one of a few options (suveryn-tracker#44): React Aria's RadioGroup, so the arrow keys move
 * between the options, Tab leaves the group, and a screen reader hears "radio button, 1 of 2".
 *
 * - RadioCards: large options with an icon, a title and a description (network mode, certificate,
 *   backup target in the setup).
 * - RadioList: compact options, each with a title and a description, and optional content under an
 *   option (the setup's approved-destination chips).
 * - Segmented: a row of short options side by side (the usage period: Hour, Day, Week, …).
 *
 * Each option's name is its title and its description is read after it (aria-labelledby and
 * aria-describedby): without that, the label wraps both and a screen reader reads the description twice.
 *
 * Styled in ui.css through [data-selected], [data-hovered], [data-focus-visible], [data-disabled].
 */
import { Check, CircleAlert } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Checkbox as AriaCheckbox, Radio, RadioGroup } from "react-aria-components";
import { useFieldError } from "./forms";

export type Choice = {
  value: string;
  title: string;
  description?: string;
  icon?: ReactNode;
  /** Shown under the option (not part of its name). */
  after?: ReactNode;
};

type Props = {
  /** The group's name for screen readers (a visible heading usually says the same). */
  label: string;
  choices: Choice[];
  value: string;
  onChange: (value: string) => void;
  name?: string;
};

export function RadioCards({ label, choices, value, onChange, name }: Props) {
  const id = useId();
  return (
    <RadioGroup aria-label={label} value={value} onChange={onChange} name={name} className="ui-radio-cards">
      {choices.map((c) => (
        <Radio key={c.value} value={c.value} className="ui-radio-card" aria-labelledby={`${id}-${c.value}-title`}
               aria-describedby={c.description ? `${id}-${c.value}` : undefined}>
          {c.icon && <span className="ui-radio-card-icon" aria-hidden>{c.icon}</span>}
          <span className="ui-radio-card-body">
            <span id={`${id}-${c.value}-title`} className="ui-radio-card-title">{c.title}</span>
            {c.description && <span id={`${id}-${c.value}`} className="ui-radio-card-desc">{c.description}</span>}
          </span>
          <span className="ui-radio-dot" aria-hidden />
        </Radio>
      ))}
    </RadioGroup>
  );
}

export function RadioList({ label, choices, value, onChange, name }: Props) {
  const id = useId();
  return (
    <RadioGroup aria-label={label} value={value} onChange={onChange} name={name} className="ui-radio-list">
      {choices.map((c) => (
        <div key={c.value} className="ui-radio-list-item">
          <Radio value={c.value} className="ui-radio-option" aria-labelledby={`${id}-${c.value}-title`}
                 aria-describedby={c.description ? `${id}-${c.value}` : undefined}>
            <span className="ui-radio-dot" aria-hidden />
            <span>
              <span id={`${id}-${c.value}-title`} className="ui-radio-option-title">{c.title}</span>
              {c.description && <span id={`${id}-${c.value}`} className="ui-radio-option-desc">{c.description}</span>}
            </span>
          </Radio>
          {c.after}
        </div>
      ))}
    </RadioGroup>
  );
}

/** A single checkbox, e.g. a confirmation the form needs; its error (from the form, by name) shows under it. */
export function Checkbox({ name, children, checked, onChange }: { name: string; children: ReactNode; checked: boolean;
                                                                  onChange: (checked: boolean) => void }) {
  const id = useId();
  const { error, clear } = useFieldError(name);
  return (
    <div className="ui-checkbox-field">
      <AriaCheckbox name={name} isSelected={checked} onChange={(v) => { clear(); onChange(v); }} className="ui-checkbox"
                    isInvalid={!!error} aria-describedby={error ? `${id}-error` : undefined}>
        <span className="ui-checkbox-box" aria-hidden><Check size={13} strokeWidth={3} /></span>
        <span>{children}</span>
      </AriaCheckbox>
      {error && (
        <span id={`${id}-error`} className="ui-field-error">
          <CircleAlert size={16} aria-hidden />
          <span>{error}</span>
        </span>
      )}
    </div>
  );
}

/** Short options side by side, one of them chosen (the usage period). One Tab stop; the arrow keys
 *  choose. */
export function Segmented({ label, options, value, onChange }: {
  label: string; options: { value: string; label: string }[]; value: string; onChange: (value: string) => void;
}) {
  return (
    <RadioGroup aria-label={label} value={value} onChange={onChange} orientation="horizontal" className="ui-segmented">
      {options.map((o) => <Radio key={o.value} value={o.value} className="ui-segment">{o.label}</Radio>)}
    </RadioGroup>
  );
}
