/**
 * The product's interface languages: the one list, and the one current choice, shared by the chat
 * (src/i18n) and the web setup (src/setup/i18n). Adding a language starts here; the full list of
 * places is in docs/translations.md. The playbooks have the same list (suveryn_playbooks.LANGUAGES);
 * a test there checks that the two agree.
 *
 * The current language is the one chosen in a language menu (remembered in this browser), else the
 * browser's preferred one when it is supported, else English. The web setup starts from the language
 * chosen at installation instead (``initialLang``).
 */
import { useSyncExternalStore } from "react";

export const LANGS = ["en", "nl", "fr"] as const;
export type Lang = (typeof LANGS)[number];

/** Each language's name in its own language, for the language menus. */
export const LANGUAGE_NAMES: Record<Lang, string> = { en: "English", nl: "Nederlands", fr: "Français" };
/** The locale for dates and numbers: UK English, Belgian Dutch and French. */
export const LOCALES: Record<Lang, string> = { en: "en-GB", nl: "nl-BE", fr: "fr-BE" };

const KEY = "suveryn.lang";  // this browser's choice, shared by the chat and the web setup
const isLang = (x: unknown): x is Lang => typeof x === "string" && (LANGS as readonly string[]).includes(x);

/** The first supported language in a list of BCP 47 tags (e.g. navigator.languages), else English. */
export function pickLang(preferred: readonly string[]): Lang {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLang(base)) return base;
  }
  return "en";
}

/** The language to start with: ``first`` if it is supported (the setup's, chosen at installation),
 *  else this browser's choice, else the browser's languages. */
export function initialLang(first: string | null = null): Lang {
  if (isLang(first)) return first;
  try {
    const saved = localStorage.getItem(KEY);
    if (isLang(saved)) return saved;
  } catch { /* storage blocked: fall back to the browser's languages */ }
  return pickLang(typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]);
}

let current: Lang = initialLang();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = LOCALES[current];

/** The current language. */
export const lang = (): Lang => current;

/** Switches the language for the page (and, with ``remember``, for this browser) and re-renders
 *  everything that reads it. */
export function setLang(next: Lang, remember = true): void {
  if (remember) { try { localStorage.setItem(KEY, next); } catch { /* this page only */ } }
  if (next === current) return;
  current = next;
  if (typeof document !== "undefined") document.documentElement.lang = LOCALES[next];
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** The current language; the component re-renders when it changes. */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, lang, lang);
}
