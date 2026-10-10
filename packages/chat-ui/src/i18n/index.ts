/**
 * The chat UI's languages (suveryn-tracker#8): English, Dutch and French string tables (en.ts,
 * nl.ts, fr.ts), the current language, and a hook that re-renders on a change.
 *
 * The language is the one chosen in the UI (remembered in this browser), else the browser's
 * preferred language when it is one of the three, else English. Keycloak's login page is opened
 * in the same language (signIn passes it on). Model answers are in the language of the question,
 * whatever the interface language.
 */
import { useSyncExternalStore } from "react";
import en, { type Messages } from "./en";
import fr from "./fr";
import nl from "./nl";

export type Lang = "en" | "nl" | "fr";
export const LANGS: Lang[] = ["en", "nl", "fr"];
const TABLES: Record<Lang, Messages> = { en, nl, fr };
const KEY = "suveryn.lang";
// Locale for dates and numbers shown by the UI: UK English, Belgian Dutch and French.
const LOCALES: Record<Lang, string> = { en: "en-GB", nl: "nl-BE", fr: "fr-BE" };

/** The first supported language in a list of BCP 47 tags (e.g. navigator.languages), else English. */
export function pickLang(preferred: readonly string[]): Lang {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split("-")[0];
    if ((LANGS as string[]).includes(base)) return base as Lang;
  }
  return "en";
}

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && (LANGS as string[]).includes(saved)) return saved as Lang;
  } catch { /* storage blocked: fall back to the browser's languages */ }
  return pickLang(typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]);
}

let current: Lang = initial();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = current;

/** The current language. */
export const lang = (): Lang => current;
/** The current language's strings, for code outside React components. */
export const t = (): Messages => TABLES[current];
/** Locale tag for dates in the current language. */
export const locale = (): string => LOCALES[current];

/** Switches the language, remembers it in this browser, and re-renders components using useT(). */
export function setLang(next: Lang): void {
  if (next === current) return;
  current = next;
  try { localStorage.setItem(KEY, next); } catch { /* remembered for this page only */ }
  if (typeof document !== "undefined") document.documentElement.lang = next;
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** The current language's strings; the component re-renders when the language changes. */
export function useT(): Messages {
  return TABLES[useSyncExternalStore(subscribe, lang, lang)];
}

export type { Messages };
/** Every language's table (the language menu shows each name in its own language; tests compare them). */
export const TABLES_FOR_TESTS = TABLES;
