/**
 * Language menu (suveryn-tracker#8): English, Nederlands, Français, each in its own language.
 * The choice is remembered in this browser; see src/i18n/index.ts.
 */
import { Languages } from "lucide-react";
import { LANGS, setLang, TABLES_FOR_TESTS as TABLES, useT, lang, type Lang } from "../i18n";

export function LanguagePicker() {
  const m = useT();
  return (
    <label className="language">
      <Languages size={14} aria-hidden />
      <span className="visually-hidden">{m.language}</span>
      <select value={lang()} onChange={(e) => setLang(e.target.value as Lang)}>
        {LANGS.map((l) => <option key={l} value={l} lang={l}>{TABLES[l].languageName}</option>)}
      </select>
    </label>
  );
}
