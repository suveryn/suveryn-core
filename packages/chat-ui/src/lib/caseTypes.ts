/**
 * The case types this appliance offers (suveryn-tracker#229): read from the server (``GET /v1/case-types``) by the first
 * screen that needs them, once, which has them from core's reference content and the installed packs, each with its
 * word per language. The screens keep no list of their own. A case whose stored type is no longer offered shows the
 * id as stored.
 */
import { useSyncExternalStore } from "react";
import { listCaseTypes, type CaseTypeInfo } from "../api";
import { lang } from "../i18n";

type State = { types: CaseTypeInfo[]; failure: string | null };
let state: State = { types: [], failure: null };
let asked = false;
const listeners = new Set<() => void>();
const subscribe = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };
const set = (next: State) => { state = next; listeners.forEach((f) => f()); };

/** Sets the list (``loadCaseTypes``, and the tests). */
export function setCaseTypes(types: CaseTypeInfo[]): void {
  set({ types, failure: null });
}

/** Reads the list from the server. A failure is kept, worded (the code's sentence), until a screen asks again
 *  (``loadCaseTypes`` once more, as the new-case dialog does when it opens): never a request per render. */
export async function loadCaseTypes(): Promise<void> {
  asked = true;
  try { setCaseTypes(await listCaseTypes()); } catch (e) { set({ ...state, failure: (e as Error).message }); }
}

/** The offered types, in the server's order, read the first time a screen asks; it re-renders when they arrive. */
export function useCaseTypes(): CaseTypeInfo[] {
  if (!asked) void loadCaseTypes();
  return useSyncExternalStore(subscribe, () => state).types;
}

/** Why the list couldn't be read, in the reader's language; null while it could. */
export function useCaseTypesFailure(): string | null {
  return useSyncExternalStore(subscribe, () => state).failure;
}

/** A type's word in the interface language (English when the pack has none in it); a type not offered: its id. */
export function caseTypeLabel(type: string, types: CaseTypeInfo[] = state.types): string {
  const t = types.find((x) => x.id === type);
  return t ? t.text[lang()] ?? t.text.en ?? type : type;
}
