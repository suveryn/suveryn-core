/**
 * A playbook's words in the interface language: its title, one line on what it does, and its fact
 * labels. The playbook carries them (suveryn_playbooks, one file per language per pack), so a new
 * playbook needs no change here; docs/translations.md.
 */
import type { PlaybookInfo } from "../api";
import type { Lang } from "../i18n/languages";

export type PlaybookWords = { title: string; summary: string; labels: Record<string, string> };

export function playbookWords(p: Pick<PlaybookInfo, "name" | "text"> | null | undefined, lang: Lang): PlaybookWords {
  return p?.text?.[lang] ?? p?.text?.en ?? { title: p?.name ?? "", summary: "", labels: {} };
}
