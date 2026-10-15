/**
 * Language menu (suveryn-tracker#8): English, Nederlands, Français, each in its own language.
 * The choice is remembered in this browser; see src/i18n/index.ts. The library's Select (#44): a
 * button that opens a list, as in the web setup.
 */
import { Languages } from "lucide-react";
import { LANGS, setLang, TABLES_FOR_TESTS as TABLES, useT, lang, type Lang } from "../i18n";
import { Select } from "../ui";

export function LanguagePicker() {
  const m = useT();
  return (
    <Select label={m.language} icon={<Languages size={14} />} value={lang()} onChange={(l) => setLang(l as Lang)}
            options={LANGS.map((l) => ({ id: l, label: TABLES[l].languageName, lang: l }))} className="language" />
  );
}
