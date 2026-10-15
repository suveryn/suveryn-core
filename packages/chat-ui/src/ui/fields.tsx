/**
 * Text fields (suveryn-tracker#44): label, input, optional hint and error, wired together by React
 * Aria (aria-describedby, aria-invalid). Errors come from the screen (shown when it is submitted,
 * never while typing; see Form in forms.tsx), in the interface's language, with an icon: the brand
 * has no error red, so an error is accent-ink plus an icon and a message.
 */
import { CircleAlert, Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import {
  FieldError,
  Group,
  Input,
  Label,
  Text,
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
