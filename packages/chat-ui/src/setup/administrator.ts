/**
 * The administrator account's rules (setup screen 2, suveryn-tracker#37): a name, an email address,
 * a password of at least 15 characters that isn't a common password and doesn't contain the name,
 * the email address or the appliance's name, typed twice. Checked when Continue is pressed, never
 * while typing. Keycloak's password policy must enforce the same rules (length(15),
 * notUsername, notEmail, passwordBlacklist), since the account lives there.
 *
 * The common-password check here is a short list for the spike: the real one needs a list of
 * leaked passwords on the appliance, shared with Keycloak's passwordBlacklist (open point, #37).
 */
import type { FieldErrors } from "../ui";
import type { Text } from "./i18n";

export const MIN_PASSWORD = 15;

const COMMON = new Set([
  "passwordpassword", "password1234567", "123456789012345", "1234567890123456", "qwertyuiopasdfgh",
  "qwertyuiopasdfghjkl", "iloveyouiloveyou", "welcomewelcome1", "azertyuiopqsdfgh", "wachtwoordwachtwoord",
  "motdepassemotdepasse", "administrator123", "adminadminadmin",
]);

/** Whether a password is too easy: on the common list, one repeated character, or a run like 0123… */
export function isCommonPassword(password: string): boolean {
  const p = password.toLowerCase();
  if (COMMON.has(p)) return true;
  if (/^(.)\1+$/.test(p)) return true;
  const codes = [...p].map((c) => c.codePointAt(0)!);
  return codes.every((c, i) => i === 0 || c - codes[i - 1] === 1);
}

/** Lower-case words of at least 4 letters from a name or an email address's local part. */
function personalWords(...values: string[]): string[] {
  return values.flatMap((v) => v.toLowerCase().split(/[^\p{L}\p{N}]+/u)).filter((w) => w.length >= 4);
}

export type Administrator = { name: string; email: string; password: string; confirm: string };

export function checkAdministrator(a: Administrator, applianceName: string, t: Text): FieldErrors {
  const errors: FieldErrors = {};
  if (!a.name.trim()) errors.name = t.errNameMissing;
  const email = a.email.trim();
  if (!email) errors.email = t.errEmailMissing;
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = t.errEmailInvalid;

  const p = a.password;
  const lower = p.toLowerCase();
  if ([...p].length < MIN_PASSWORD) errors.password = t.errPasswordShort(MIN_PASSWORD);
  else if (isCommonPassword(p)) errors.password = t.errPasswordCommon;
  else if (personalWords(a.name, email.split("@")[0], applianceName).some((w) => lower.includes(w))) {
    errors.password = t.errPasswordPersonal;
  }
  if (!errors.password && a.confirm !== p) errors.confirm = t.errConfirm;
  return errors;
}
