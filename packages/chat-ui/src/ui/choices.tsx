/**
 * Choosing one of a few options (suveryn-tracker#44): React Aria's RadioGroup, so the arrow keys move
 * between the options, Tab leaves the group, and a screen reader hears "radio button, 1 of 2".
 *
 * - RadioCards: large options with an icon, a title and a description (network mode, certificate,
 *   backup target in the setup).
 * - RadioList: compact options, each with a title and a description, and optional content under an
 *   option (the setup's approved-destination chips).
 *
 * Styled in ui.css through [data-selected], [data-hovered], [data-focus-visible], [data-disabled].
 */
import { useId, type ReactNode } from "react";
import { Radio, RadioGroup } from "react-aria-components";

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
        <Radio key={c.value} value={c.value} className="ui-radio-card"
               aria-describedby={c.description ? `${id}-${c.value}` : undefined}>
          {c.icon && <span className="ui-radio-card-icon" aria-hidden>{c.icon}</span>}
          <span className="ui-radio-card-body">
            <span className="ui-radio-card-title">{c.title}</span>
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
          <Radio value={c.value} className="ui-radio-option" aria-describedby={c.description ? `${id}-${c.value}` : undefined}>
            <span className="ui-radio-dot" aria-hidden />
            <span>
              <span className="ui-radio-option-title">{c.title}</span>
              {c.description && <span id={`${id}-${c.value}`} className="ui-radio-option-desc">{c.description}</span>}
            </span>
          </Radio>
          {c.after}
        </div>
      ))}
    </RadioGroup>
  );
}
