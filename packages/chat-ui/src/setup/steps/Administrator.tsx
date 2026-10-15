/**
 * Setup step 2: Administrator account (design web-02-administrator.html). Errors appear on Continue
 * only, under the field, and the focus moves to the first one; no checklist on screen.
 */
import { Info } from "lucide-react";
import { useState } from "react";
import { Button, Form, Note, PasswordField, TextField } from "../../ui";
import { checkAdministrator } from "../administrator";
import type { Answers } from "../api";
import { useText } from "../text";

type Props = {
  applianceName: string;
  answers: Answers["administrator"];
  onBack: () => void;
  onDone: (administrator: NonNullable<Answers["administrator"]>) => void;
  headingId: string;
};

export function Administrator({ applianceName, answers, onBack, onDone, headingId }: Props) {
  const t = useText();
  const [name, setName] = useState(answers?.name ?? "");
  const [email, setEmail] = useState(answers?.email ?? "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  return (
    <Form
      aria-labelledby={headingId}
      check={() => checkAdministrator({ name, email, password, confirm }, applianceName, t)}
      onValid={() => onDone({ name: name.trim(), email: email.trim() })}
    >
      <h1 id={headingId} className="setup-title">{t.adminTitle}</h1>
      <p className="setup-lead">{t.adminLead}</p>

      <TextField name="name" label={t.fullName} placeholder={t.fullNamePlaceholder} autoComplete="name"
                 value={name} onChange={setName} />
      <TextField name="email" type="email" label={t.email} placeholder={t.emailPlaceholder} autoComplete="username"
                 description={t.emailHint} value={email} onChange={setEmail} />
      <PasswordField name="password" label={t.password} placeholder={t.passwordPlaceholder} autoComplete="new-password"
                     showLabel={t.showPassword} value={password} onChange={setPassword} />
      <PasswordField name="confirm" label={t.confirmPassword} placeholder={t.confirmPlaceholder} autoComplete="new-password"
                     value={confirm} onChange={setConfirm} />
      <Note icon={<Info size={16} />}>{t.adminNote}</Note>

      <div className="setup-footer">
        <Button onPress={onBack}>{t.back}</Button>
        <Button type="submit" variant="primary">{t.continue}</Button>
      </div>
    </Form>
  );
}
