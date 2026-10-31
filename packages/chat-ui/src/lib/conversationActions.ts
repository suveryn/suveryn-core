/**
 * What a conversation's menu offers (docs/design/chat-ui.md §3 and §4), kept apart from the column and
 * the overview so both say the same and it can be tested. An action without the right is shown
 * disabled, never hidden; the server still decides (routes/conversations.py).
 *
 * - *Pin* / *Unpin*: a personal conversation of one's own. One in a case follows its case: disabled,
 *   with the reason "Pin the case instead".
 * - *Rename* and *Delete*: one's own.
 * - *Move to a case*: one's own personal conversation, into an open case one contributes to.
 */
import type { Case, ConversationSummary } from "../api";

export type ConversationAction = "open" | "pin" | "unpin" | "rename" | "move" | "delete";
export type ActionState = { id: ConversationAction; disabled: boolean; reason?: "followsCase" };

/** More than this many pinned conversations shows the hint "Five pinned. A case keeps them together." */
export const PIN_HINT_AFTER = 5;

export function isOwn(c: Pick<ConversationSummary, "owner">, me: string | undefined): boolean {
  return !c.owner || c.owner === me;
}

/** The menu's actions in their order, *Open* first when the list doesn't open a row by itself. */
export function conversationActions(c: ConversationSummary, me: string | undefined, withOpen = false): ActionState[] {
  const own = isOwn(c, me);
  const inCase = !!c.case_id;
  return [
    ...(withOpen ? [{ id: "open" as const, disabled: false }] : []),
    { id: c.pinned ? "unpin" : "pin", disabled: inCase || !own, ...(inCase ? { reason: "followsCase" as const } : {}) },
    { id: "rename", disabled: !own },
    { id: "move", disabled: inCase || !own },
    // a playbook run's conversation goes with its case: stop or cancel the run instead (docs/design/playbooks.md)
    { id: "delete", disabled: !own || !!c.run_id },
  ];
}

/** The personal conversations pinned in the column, after the pinned cases (§2). */
export function pinnedConversations(list: ConversationSummary[]): ConversationSummary[] {
  return list.filter((c) => c.pinned && !c.case_id);
}

/** The cases a personal conversation can move into: open, and the person contributes to or manages them. */
export function moveTargets(cases: Case[]): Case[] {
  return cases.filter((c) => c.state === "open" && (c.my_role === "contributor" || c.my_role === "manager"))
    .sort((a, b) => a.reference.localeCompare(b.reference));
}
