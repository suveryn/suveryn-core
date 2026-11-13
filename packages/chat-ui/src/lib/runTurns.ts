/**
 * A playbook run's thread in the reader's language. The server stores a playbook's own turn as its meaning only (its
 * kind and facts, never a sentence), and a person's button or form answer as the values given; this module words both
 * (decision of 12 November 2026, *Meaning on the server, words at the edge*). The kinds are the server's
 * `turn_kinds.json`, which this module's test reads, so a kind the screen can't word fails. A turn stored before the
 * decision has its text, shown as it is.
 */
import type { Messages } from "../i18n";
import type { RunTurn } from "../api";
import { factLabel, optionLabel, type PlaybookWords } from "./playbooks";

/** A playbook turn's meaning (`meta`), as the server writes it. */
export type TurnMeta = {
  kind?: string; step?: string; facts?: string[]; found?: number; total?: number; fact?: string; value?: string;
  documents?: string[]; reads?: string[]; reason?: string;
};

/** The kinds a run's line in the middle shows (who did what, when), not the playbook speaking. */
export const EVENTS = new Set(["paused", "resumed", "stopped", "cancelled", "confirmed"]);

/** What the playbook says in a turn, in the reader's language; the checkpoint's line when no review shows under it. */
export function playbookTurnText(meta: TurnMeta, m: Messages, words: PlaybookWords): string {
  const label = (id: string) => factLabel(words, id);
  const step = (id: string | undefined) => words.steps?.[id ?? ""] ?? id ?? "";
  switch (meta.kind) {
    case "request": return words.questions?.[meta.step ?? ""] ?? "";
    case "ask": return m.runAskTurn({ found: meta.found ?? 0, total: meta.total ?? 0, list: (meta.facts ?? []).map(label).join(", ") });
    case "skipped_step": return meta.value
      ? m.runStepNotNeeded({ step: step(meta.step), fact: label(meta.fact ?? ""), option: optionLabel(words, meta.fact ?? "", meta.value) })
      : m.runStepUnknown({ step: step(meta.step), fact: label(meta.fact ?? "") });
    case "checkpoint": return m.pbReviewIntroNone({ found: meta.found ?? 0, total: meta.total ?? 0 });
    case "changed": return m.runChanged({ label: label(meta.fact ?? ""), value: optionLabel(words, meta.fact ?? "", meta.value ?? "") });
    case "unplaced": return meta.facts ? m.runUnplacedAsk : m.runUnplacedChange;
    case "already_unknown": return m.runAlreadyUnknown({ facts: (meta.facts ?? []).map(label).join(", ") });
    case "read_in_part": return m.runReadInPart({ documents: (meta.documents ?? []).join(", ") });
    case "late_documents": return m.runLateDocuments({ documents: (meta.documents ?? []).join(", "), step: step(meta.step), count: (meta.documents ?? []).length, again: (meta.reads ?? []).length > 0 });
    default: return "";
  }
}

/** An event's line: who paused, resumed, stopped, cancelled or confirmed the run, and when. */
export function eventText(meta: TurnMeta, who: string, at: string, m: Messages): string {
  switch (meta.kind) {
    case "confirmed": return m.runConfirmedLine({ name: who, time: at });
    case "paused": return m.runPausedLine({ name: who, time: at });
    case "resumed": return m.runResumedLine({ name: who, time: at });
    case "stopped": return m.runStoppedLine({ name: who, time: at });
    default: return meta.reason ? m.runCancelledLineReason({ name: who, time: at, reason: meta.reason }) : m.runCancelledLine({ name: who, time: at });
  }
}

/** A person's turn: what they wrote, or else what their button or form said, in the reader's language. */
export function personTurnText(turn: Pick<RunTurn, "text" | "meta">, m: Messages, words: PlaybookWords): string {
  if (turn.text) return turn.text;
  const meta = turn.meta as { answers?: Record<string, string>; none?: boolean; case_documents?: boolean; unknown?: boolean };
  if (meta.none) return m.runNoDocument;
  if (meta.case_documents) return m.runUseCaseDocuments;
  if (meta.unknown) return m.answerPlaceholder;
  const given = Object.entries(meta.answers ?? {}).filter(([, v]) => v.trim());
  return given.length ? given.map(([f, v]) => `${factLabel(words, f)}: ${optionLabel(words, f, v)}`).join("\n")
    : meta.answers ? m.answerPlaceholder : "";
}
