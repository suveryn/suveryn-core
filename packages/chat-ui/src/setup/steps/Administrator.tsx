/**
 * Setup step 2: Administrator account (design web-02-administrator.html). Errors appear on Continue
 * only, under the field, and the focus moves to the first one; no checklist on screen.
 */
import { Info } from "lucide-react";
import { useState } from "react";
import { Form, Note, PasswordField, TextField } from "../../ui";
import { checkAdministrator, LIMITS } from "../administrator";
import { saveAdministrator, type AdministratorAnswer, type SetupState } from "../api";
import { useText } from "../i18n";
import { checkThenSave, StepFooter } from "./common";

type Props = {
  state: SetupState;
  onBack: () => void;
  onDone: (administrator: AdministratorAnswer) => void;
  headingId: string;
};

/** The password is sent to the appliance once, on Continue, and isn't kept in the page afterwards:
 *  coming back to this step asks for it again. */
export function Administrator({ state, onBack, onDone, headingId }: Props) {
  const t = useText();
  const [name, setName] = useState(state.answers.administrator?.name ?? "");
  const [email, setEmail] = useState(state.answers.administrator?.email ?? "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  return (
    <Form
      aria-labelledby={headingId}
      check={() => checkThenSave(checkAdministrator({ name, email, password, confirm }, state.name, t),
                                 () => saveAdministrator({ name: name.trim(), email: email.trim(), password }), t)}
      onValid={() => onDone({ name: name.trim(), email: email.trim() })}
    >
      <h1 id={headingId} className="setup-title">{t.adminTitle}</h1>
      <p className="setup-lead">{t.adminLead}</p>

      <TextField name="name" label={t.fullName} placeholder={t.fullNamePlaceholder} autoComplete="name" maxLength={LIMITS.name_max}
                 value={name} onChange={setName} />
      <TextField name="email" type="email" label={t.email} placeholder={t.emailPlaceholder} autoComplete="username" maxLength={LIMITS.email_max}
                 description={t.emailHint} value={email} onChange={setEmail} />
      <PasswordField name="password" label={t.password} placeholder={t.passwordPlaceholder({ min: LIMITS.password_min })} autoComplete="new-password" maxLength={LIMITS.password_max}
                     showLabel={t.showPassword} description={t.passwordMax({ max: LIMITS.password_max })} value={password} onChange={setPassword} />
      <PasswordField name="confirm" label={t.confirmPassword} placeholder={t.confirmPlaceholder} autoComplete="new-password" maxLength={LIMITS.password_max}
                     value={confirm} onChange={setConfirm} />
      <Note icon={<Info size={16} />}>{t.adminNote}</Note>

      <StepFooter onBack={onBack} back={t.back} next={t.continue} />
    </Form>
  );
}
