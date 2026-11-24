/**
 * An answer's versions (suveryn-tracker#251, board 81): the server keeps a conversation as a tree, as Claude and ChatGPT
 * do, so *Regenerate* gives a question another answer and the earlier ones stay, each with what followed it. The
 * screen shows one branch (``shown``) and keeps every turn it knows (``tree``): the ones read back, and the ones asked
 * here once the server numbered them. Switching an answer's version changes everything below it to that version's
 * branch; nothing above it changes.
 */
import type { Turn } from "../types";

/** The newest turn that follows ``turn``, and the newest that follows that, to the end: a version's branch. */
export function branchFrom(tree: Turn[], start: Turn): Turn[] {
  const path = [start];
  for (let at = start; path.length <= tree.length;) {
    const next = tree.filter((t) => t.parent === at.seq && at.seq !== undefined).at(-1);
    if (!next) break;
    path.push(next);
    at = next;
  }
  return path;
}

/** The turns this page knows, with the ones shown that the server has numbered since (a question asked here, its
 *  answer once stored), in the server's order. A turn shown over one it knows keeps what it followed. */
export function withShown(tree: Turn[], shown: Turn[]): Turn[] {
  const known = new Map(tree.map((t) => [t.seq, t]));
  let changed = false;
  for (const t of shown) {
    if (t.seq === undefined) continue;  // refused, or not stored yet: not the server's
    const was = known.get(t.seq);
    if (was === t) continue;
    if (was && same(was, { ...was, ...t, parent: t.parent ?? was.parent } as Turn)) continue;
    known.set(t.seq, (was ? { ...was, ...t, parent: t.parent ?? was.parent } : t) as Turn);
    changed = true;
  }
  return changed ? [...known.values()].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)) : tree;  // the same list when nothing is new
}

const same = (a: Turn, b: Turn) => Object.keys({ ...a, ...b }).every((k) => (a as Record<string, unknown>)[k] === (b as Record<string, unknown>)[k]);

/** The versions of the answer shown at ``i``: its question's answers, oldest first, and which of them it is. One being
 *  written (not numbered yet) is the newest. Null when there is one, or when its question isn't the server's. */
export function versionsOf(tree: Turn[], shown: Turn[], i: number): { n: number; total: number; versions: Turn[] } | null {
  const question = shown[i - 1], answer = shown[i];
  if (answer?.role !== "assistant" || question?.role !== "user" || question.seq === undefined) return null;
  const versions = tree.filter((t) => t.role === "assistant" && t.parent === question.seq);
  const at = versions.findIndex((t) => t.seq !== undefined && t.seq === answer.seq);
  const total = at < 0 ? versions.length + 1 : versions.length;
  return total < 2 ? null : { n: at < 0 ? total : at + 1, total, versions };
}

/** The conversation shown with the answer at ``i`` switched to ``version``: everything above it as it was, from it on
 *  the version's branch. */
export function switchedTo(tree: Turn[], shown: Turn[], i: number, version: Turn): Turn[] {
  return [...shown.slice(0, i), ...branchFrom(tree, version)];
}
