/**
 * A playbook's words in the interface language: its title, one line on what it does, and its fact
 * labels. The playbook carries them (suveryn_playbooks, one file per language per pack), so a new
 * playbook needs no change here; docs/translations.md.
 */
import type { PlaybookInfo } from "../api";
import type { Lang } from "../i18n/languages";

export type PlaybookWords = { title: string; summary: string; labels: Record<string, string>; questions?: Record<string, string>;
                              checks?: Record<string, string>; steps?: Record<string, string>; facts_title?: string };

/** A choice's option in words: `labels["contribution_kind.cash"]`, else the option id. */
export const optionLabel = (words: Pick<PlaybookWords, "labels">, fact: string, option: string) => words.labels[`${fact}.${option}`] ?? option;

export function playbookWords(p: Pick<PlaybookInfo, "name" | "text"> | null | undefined, lang: Lang): PlaybookWords {
  return p?.text?.[lang] ?? p?.text?.en ?? { title: p?.name ?? "", summary: "", labels: {} };
}

// ------------------------------------------------------------------ paths (format 3, suveryn_playbooks.paths)

const PATH = /^([a-z][a-z0-9_]*)(?:\[([1-9][0-9]?)\](?:\.([a-z][a-z0-9_]*))?)?$/;

/** A fact id taken apart: `price` → root only; `founders[2].name` → the list, the entry's number and the field; `conditions[1]` → no field. */
export function splitPath(id: string): { root: string; index: number | null; field: string | null } {
  const m = PATH.exec(id);
  if (!m) return { root: id, index: null, field: null };
  return { root: m[1], index: m[2] ? Number(m[2]) : null, field: m[3] ?? null };
}

export const entryPath = (list: string, index: number, field?: string | null) => `${list}[${index}]` + (field ? `.${field}` : "");

/** A fact's label by its id, a list's entries by path: `founders[2].name` → "Founder(s) 2 · Name" (the list's label, the
 *  entry's number, the field's label from `labels["founders.name"]`); `conditions[1]` → "Conditions 1". Unknown: the id. */
export function factLabel(words: Pick<PlaybookWords, "labels">, id: string): string {
  const { root, index, field } = splitPath(id);
  if (index === null) return words.labels[id] ?? id;
  const head = `${words.labels[root] ?? root} ${index}`;
  return field ? `${head} · ${words.labels[`${root}.${field}`] ?? field}` : head;
}

/** The facts as a person sees them: a list's own "the documents name none" is left out once the list has entries. */
export function shownFacts<F extends { id: string }>(facts: F[]): F[] {
  const withEntries = new Set(facts.map((f) => splitPath(f.id)).filter((p) => p.index !== null).map((p) => p.root));
  return facts.filter((f) => !withEntries.has(f.id));
}

/** The number the next entry of a list gets: one past the highest the run has. */
export function nextEntry(facts: { id: string }[], list: string): number {
  return Math.max(0, ...facts.map((f) => splitPath(f.id)).filter((p) => p.root === list && p.index !== null).map((p) => p.index as number)) + 1;
}

// ------------------------------------------------------------------ facts as the boards count and show them (P01, P03)

/** One fact as a person counts it: a plain fact, or a whole list with its entries' values (board P01: "12 of 13",
 *  a list is one fact). ``facts``: the plain fact, or the list's values by path (or its own "none" when it has no entries). */
export type FactGroup<F> = { id: string; list: boolean; facts: F[] };

/** The facts grouped as a person counts them, in the run's order (a list where its first value is). ``lists``: the
 *  playbook's list facts, so a list the documents named no entries of is a list too. */
export function factGroups<F extends { id: string }>(facts: F[], lists: Record<string, unknown> = {}): FactGroup<F>[] {
  const out = new Map<string, FactGroup<F>>();
  for (const f of shownFacts(facts)) {
    const { root, index } = splitPath(f.id);
    const g = out.get(root) ?? { id: root, list: root in lists, facts: [] };
    if (index !== null) g.list = true;
    g.facts.push(f);
    out.set(root, g);
  }
  return [...out.values()];
}

/** Whether a fact as counted has a value: a plain one its own (or the confirmed one), a list any entry's. */
export const groupFound = (g: FactGroup<{ value: string; confirmed?: string | null }>) =>
  g.facts.some((f) => !!(f.confirmed ?? f.value));

/** A list's entries in order, each its values by field ("" for a list of plain values). */
export function entriesOf<F extends { id: string }>(g: FactGroup<F>): { index: number; values: Record<string, F> }[] {
  const by = new Map<number, Record<string, F>>();
  for (const f of g.facts) {
    const { index, field } = splitPath(f.id);
    if (index === null) continue;
    by.set(index, { ...(by.get(index) ?? {}), [field ?? ""]: f });
  }
  return [...by.entries()].sort(([a], [b]) => a - b).map(([index, values]) => ({ index, values }));
}
