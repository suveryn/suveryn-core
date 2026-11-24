/**
 * A conversation as the page keeps it (suveryn-tracker#251, board 81): the server keeps it as a tree, as ChatGPT and
 * Claude do, so *Regenerate* gives a question another answer and the earlier ones stay, each with what followed it.
 * The page keeps one list of every turn it knows, each naming the turn it follows (``follows``, its id), and the last
 * turn shown (``leaf``), as ChatGPT's client keeps its ``mapping`` and ``current_node``. The branch on screen is worked
 * out from these (``shownOf``): never kept beside them.
 */
import type { AssistantTurn, Turn, UserTurn } from "../types";

export type Conversation = { turns: Turn[]; leaf: string | null };
export const NO_CONVERSATION: Conversation = { turns: [], leaf: null };

/** The branch shown: the last turn shown, and the turn it follows, back to the first. */
export function shownOf(c: Conversation): Turn[] {
  const byId = new Map(c.turns.map((t) => [t.id, t]));
  const path: Turn[] = [];
  for (let at = c.leaf ? byId.get(c.leaf) : undefined; at && path.length < c.turns.length; at = at.follows ? byId.get(at.follows) : undefined) {
    path.push(at);
  }
  return path.reverse();
}

/** From the turn ``from`` (null: the start), the newest turn that follows it, and the newest that follows that, to
 *  the end: the last turn of its newest branch. Newest is last in the list: the server's order, then what was asked
 *  here. */
function newestLeaf(turns: Turn[], from: string | null): string | null {
  let at = from;
  for (let steps = 0; steps <= turns.length; steps++) {
    const next = turns.filter((t) => (t.follows ?? null) === at).at(-1);
    if (!next) break;
    at = next.id;
  }
  return at;
}

/** A conversation read back: every turn, the newest answer of each question shown, and what followed it. */
export const opened = (turns: Turn[]): Conversation => ({ turns, leaf: newestLeaf(turns, null) });

/** The conversation read again from the server (after a document was deleted, which the server cleaned out of every
 *  turn): its turns as stored, still showing the branch that was shown, found by the number the server gave its last
 *  turn; the newest branch if that has none yet. */
export function readAgain(was: Conversation, read: Conversation): Conversation {
  const seq = was.turns.find((t) => t.id === was.leaf)?.seq;
  const leaf = seq === undefined ? undefined : read.turns.find((t) => t.seq === seq)?.id;
  return leaf ? { ...read, leaf } : read;
}

/** A question asked after the turn shown last, and its answer being written, shown. */
export function asked(c: Conversation, question: UserTurn, answer: AssistantTurn): Conversation {
  return { turns: [...c.turns, { ...question, follows: c.leaf }, { ...answer, follows: question.id }], leaf: answer.id };
}

/** Regenerate: another answer to a question already there, shown in place of the one that was (which stays). */
export function answeredAgain(c: Conversation, questionId: string, answer: AssistantTurn): Conversation {
  return { turns: [...c.turns, { ...answer, follows: questionId }], leaf: answer.id };
}

/** Without these turns (a question asked again with the case's documents read again): what is shown ends at the
 *  nearest turn left that it followed. */
export function without(c: Conversation, ids: Set<string>): Conversation {
  const byId = new Map(c.turns.map((t) => [t.id, t]));
  let leaf = c.leaf;
  while (leaf && ids.has(leaf)) leaf = byId.get(leaf)?.follows ?? null;
  return { turns: c.turns.filter((t) => !ids.has(t.id)), leaf };
}

/** Regenerate on the answer shown at ``i``. A question the server stored is asked once more as it was asked
 *  (``asking``, its number) and answered under itself (``question``): one more version of its answers. One it never
 *  stored (refused): the failed pair goes and the question is asked anew, as a new question, never a version the
 *  server doesn't keep (review of the one list). */
export function regenerating(c: Conversation, shown: Turn[], i: number): { conversation: Conversation; asking?: number; question?: UserTurn } {
  const question = shown[i - 1] as UserTurn, asking = question.seq;
  return asking === undefined ? { conversation: without(c, new Set([question.id, shown[i].id])) } : { conversation: c, asking, question };
}

/** The versions of the answer shown at ``i``: its question's answers, oldest first, and which of them it is. Null
 *  when there is one, or when its question isn't the server's (nothing kept to ask again). */
export function versionsOf(c: Conversation, shown: Turn[], i: number): { n: number; total: number; versions: Turn[] } | null {
  const question = shown[i - 1], answer = shown[i];
  if (answer?.role !== "assistant" || question?.role !== "user" || question.seq === undefined) return null;
  const versions = c.turns.filter((t) => t.role === "assistant" && t.follows === question.id);
  const n = versions.indexOf(answer) + 1;
  return versions.length < 2 || n === 0 ? null : { n, total: versions.length, versions };
}

/** Switched to ``version``: everything above it as it was, from it on its newest branch. */
export const switchedTo = (c: Conversation, version: Turn): Conversation => ({ ...c, leaf: newestLeaf(c.turns, version.id) });
