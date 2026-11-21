/**
 * The case types this appliance offers (suveryn-tracker#229): read from the server (``GET /v1/case-types``) by the first
 * screen that needs them, once,
 * which has them from core's reference content and the installed packs, each with its word per language. The screens
 * keep no list of their own. A case whose stored type is no longer offered shows the id as stored.
 */
import { useSyncExternalStore } from "react";
import { listCaseTypes, type CaseTypeInfo } from "../api";
import { lang } from "../i18n";

let known: CaseTypeInfo[] = [];
let asked = false;
const listeners = new Set<() => void>();
const subscribe = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };

/** Sets the list (``loadCaseTypes``, and the tests). */
export function setCaseTypes(types: CaseTypeInfo[]): void {
  known = types;
  listeners.forEach((f) => f());
}

/** Reads the list from the server; on a failure the list stays as it was (a type then shows by its id). */
export async function loadCaseTypes(): Promise<void> {
  asked = true;
  try { setCaseTypes(await listCaseTypes()); } catch { asked = false; /* a type shows by its id until a screen asks again */ }
}

/** The offered types, in the server's order, read the first time a screen asks; it re-renders when they arrive. */
export function useCaseTypes(): CaseTypeInfo[] {
  if (!asked) void loadCaseTypes();
  return useSyncExternalStore(subscribe, () => known);
}

/** A type's word in the interface language (English when the pack has none in it); a type not offered: its id. */
export function caseTypeLabel(type: string, types: CaseTypeInfo[] = known): string {
  const t = types.find((x) => x.id === type);
  return t ? t.text[lang()] ?? t.text.en ?? type : type;
}
