/**
 * Moving between places, cases, conversations and playbook runs: the decisions App.tsx makes, apart from React so
 * they can be tested (audit of 4 November 2026, App.tsx in slices; lib/ask.ts, lib/documentActions.ts and the
 * composer's cards in lib/uploads.ts came first). What stays in App.tsx is the state these decisions set.
 */
import type { ConversationSummary, Member, PlaybookInfo, Run } from "../api";
import type { CaseAction } from "../components/Sidebar";
import type { Turn } from "../types";
import { restoreAbout } from "./askAbout";
import type { Message } from "./messages";
import { fromSaved, toSaved } from "./conversations";
import { PIN_HINT_AFTER, pinnedConversations } from "./conversationActions";
import { restoreThinking } from "./thinking";

/** Whether something listed elsewhere (a conversation, a document) lives in another place than the open one:
 *  a case's id, or null for the personal space. The page goes there first. */
export function inAnotherPlace(target: string | null | undefined, current: string | null): boolean {
  return (target ?? null) !== current;
}

/** The case menu's actions that need the case open behind them: its members, its log, closing it. */
export function needsCaseOpen(action: CaseAction): boolean {
  return action === "members" || action === "log" || action === "close";
}

/** The run's own playbook (the manifest it started under), whatever is installed now. */
export function runPlaybook(run: Run | null): PlaybookInfo | null {
  return run?.playbook ?? null;
}

/** A run still going: reading, waiting for an answer, or paused. */
export const runIsLive = (run: Pick<Run, "status"> | null): boolean => !!run && ["reading", "waiting", "paused"].includes(run.status);

/** A member's name by username, as the case knows them; the username when they aren't a member. */
export function memberName(members: Pick<Member, "username" | "name">[], username: string): string {
  return members.find((p) => p.username === username)?.name || username;
}

/** Starting a playbook was refused because a run of that playbook is live in the case: the run the gateway names
 *  (`run.already_going`, its value `run`), to open instead. One live run per playbook per case (handover of 30
 *  October 2026, board 53). Never a run guessed from the case's live runs, which may be another playbook's
 *  (suveryn-tracker#181). */
export function liveRunInstead(problem: Pick<Message, "code" | "params"> | undefined): string | null {
  const run = problem?.code === "run.already_going" ? problem.params?.run : undefined;
  return typeof run === "string" && run ? run : null;
}

/** Pinning one more personal conversation past PIN_HINT_AFTER says once that a case keeps them together (§3). */
export function pinHintDue(all: ConversationSummary[], id: string, pinned: boolean, shownBefore: boolean): boolean {
  return pinned && !shownBefore && pinnedConversations(all).filter((x) => x.id !== id).length + 1 > PIN_HINT_AFTER;
}

/** A saved conversation opened: its turns, what it was asking about (§10), Fast or Thorough (§5), and the saved form
 *  to compare with, so the unchanged turns aren't saved again. */
export function reopened(saved: Turn[], thinkingByDefault: boolean) {
  const turns = fromSaved(saved);
  return { turns, about: restoreAbout(turns), thinking: restoreThinking(turns, thinkingByDefault), lastSaved: JSON.stringify(toSaved(turns)) };
}

/** Signing out asks first, keep or delete, when there are saved conversations to keep. */
export const asksBeforeSignOut = (historyReady: boolean, conversations: number): boolean => historyReady && conversations > 0;
