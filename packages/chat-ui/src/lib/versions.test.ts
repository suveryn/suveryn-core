/** A conversation as the page keeps it (board 81, suveryn-tracker#251): one list of every turn known, each naming the
 *  turn it follows, and the last one shown; the branch on screen is worked out from these. */
import { describe, expect, it } from "vitest";
import type { AssistantTurn, Turn, UserTurn } from "../types";
import { askedAgain, canRegenerate } from "./ask";
import { answeredAgain, asked, NO_CONVERSATION, opened, shownOf, switchedTo, versionsOf, without } from "./versions";

const q = (seq: number, follows: string | null): UserTurn => ({ id: `q${seq}`, seq, follows, byServer: true, role: "user", text: `q${seq}`, attachments: [] });
const a = (seq: number, follows: string, status: AssistantTurn["status"] = "done"): AssistantTurn =>
  ({ id: `a${seq}`, seq, follows, byServer: true, role: "assistant", text: `a${seq}`, citations: [], status, grounded: false });
const writing = (id: string): AssistantTurn => ({ id, role: "assistant", text: "", citations: [], status: "streaming", grounded: false });
// q1 answered twice (Regenerate): a2 with its follow-up q4/a5, then a3 with none
const all: Turn[] = [q(1, null), a(2, "q1"), a(3, "q1"), q(4, "a2"), a(5, "q4")];
const ids = (turns: Turn[]) => turns.map((t) => t.id);

describe("a conversation the page keeps", () => {
  it("opened, shows the newest answer of each question and what followed it", () => {
    expect(ids(shownOf(opened(all)))).toEqual(["q1", "a3"]);
    expect(ids(shownOf(opened([q(1, null), a(2, "q1"), q(3, "a2"), a(4, "q3")])))).toEqual(["q1", "a2", "q3", "a4"]);
    expect(shownOf(NO_CONVERSATION)).toEqual([]);
  });

  it("an answer's versions are its question's answers, oldest first; one being written is the newest", () => {
    const c = opened(all);
    expect(versionsOf(c, shownOf(c), 1)).toMatchObject({ n: 2, total: 2 });
    const first = switchedTo(c, all[1]);
    expect(versionsOf(first, shownOf(first), 1)).toMatchObject({ n: 1, total: 2 });
    expect(versionsOf(first, shownOf(first), 3)).toBeNull();  // one version: no arrows
    const again = answeredAgain(c, "q1", writing("new"));
    expect(ids(shownOf(again))).toEqual(["q1", "new"]);
    expect(versionsOf(again, shownOf(again), 1)).toMatchObject({ n: 3, total: 3 });
    const local = asked(NO_CONVERSATION, { ...q(1, null), seq: undefined }, writing("w"));
    expect(versionsOf(local, shownOf(local), 1)).toBeNull();  // its question isn't the server's
  });

  it("switching changes everything below the answer to that version's newest branch, nothing above", () => {
    const first = switchedTo(opened(all), all[1]);
    expect(ids(shownOf(first))).toEqual(["q1", "a2", "q4", "a5"]);  // back to the first answer, with what followed it
    expect(ids(shownOf(switchedTo(first, all[2])))).toEqual(["q1", "a3"]);  // the second has no follow-up
    expect(first.turns).toBe(all);  // the turns known don't change
  });

  it("a question asked follows the turn shown last; taken out, what is shown ends at what it followed", () => {
    const c = asked(switchedTo(opened(all), all[1]), { ...q(6, null), seq: undefined }, writing("w"));
    expect(ids(shownOf(c))).toEqual(["q1", "a2", "q4", "a5", "q6", "w"]);
    expect(c.turns.find((t) => t.id === "q6")?.follows).toBe("a5");
    expect(ids(shownOf(without(c, new Set(["q6", "w"]))))).toEqual(["q1", "a2", "q4", "a5"]);
    // asked again, the question stays: only the new answer goes
    const again = answeredAgain(opened(all), "q1", writing("w"));
    expect(ids(shownOf(without(again, new Set(["w"]))))).toEqual(["q1"]);
  });

  it("Regenerate on a question the server refused: the failed pair goes and it is asked anew, never a version", () => {
    // review of the one list: hung under the refused question, it showed 2 of 2 the server never kept, and a
    // follow-up from the refusal was filed under the other answer
    const refused = { ...q(3, "a2"), seq: undefined, byServer: undefined }, failed = { ...a(4, "q3", "error"), seq: undefined };
    const c = asked(opened([q(1, null), a(2, "q1")]), refused, failed);
    const shown = shownOf(c);
    expect(canRegenerate(shown, 3, { busy: false, disabled: false, savedConversations: true })).toBe(true);
    expect(askedAgain(refused, true)).toBeUndefined();  // nothing stored to ask again: App asks it anew
    const anew = asked(without(c, new Set(["q3", "a4"])), { ...refused, id: "q5" }, writing("w"));
    expect(ids(shownOf(anew))).toEqual(["q1", "a2", "q5", "w"]);
    expect(versionsOf(anew, shownOf(anew), 3)).toBeNull();
  });
});
