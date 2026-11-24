/** An answer's versions (board 81, suveryn-tracker#251): the tree the server keeps, one branch shown. */
import { describe, expect, it } from "vitest";
import type { AssistantTurn, Turn, UserTurn } from "../types";
import { branchFrom, switchedTo, versionsOf, withShown } from "./versions";

const q = (seq: number, parent: number | null): UserTurn => ({ id: `q${seq}`, seq, parent, byServer: true, role: "user", text: `q${seq}`, attachments: [] });
const a = (seq: number, parent: number, status: AssistantTurn["status"] = "done"): AssistantTurn =>
  ({ id: `a${seq}`, seq, parent, byServer: true, role: "assistant", text: `a${seq}`, citations: [], status, grounded: false });
// q1 answered twice (Regenerate): a2 with its follow-up q4/a5, then a3 with none
const tree: Turn[] = [q(1, null), a(2, 1), a(3, 1), q(4, 2), a(5, 4)];
const ids = (turns: Turn[]) => turns.map((t) => t.id);

describe("an answer's versions", () => {
  it("are its question's answers, oldest first; one being written is the newest", () => {
    const shown = [q(1, null), a(3, 1)];
    expect(versionsOf(tree, shown, 1)).toMatchObject({ n: 2, total: 2 });
    expect(versionsOf(tree, [q(1, null), a(2, 1), q(4, 2), a(5, 4)], 1)).toMatchObject({ n: 1, total: 2 });
    expect(versionsOf(tree, [q(1, null), a(2, 1), q(4, 2), a(5, 4)], 3)).toBeNull();  // one version: no arrows
    const writing = { id: "new", role: "assistant", text: "", citations: [], status: "streaming", grounded: false } as Turn;
    expect(versionsOf(tree, [q(1, null), writing], 1)).toMatchObject({ n: 3, total: 3 });
    expect(versionsOf(tree, [{ ...q(1, null), seq: undefined }, writing], 1)).toBeNull();  // its question isn't the server's
  });

  it("switching changes everything below the answer to that version's branch, nothing above", () => {
    const shown = [q(1, null), a(3, 1)];
    const first = switchedTo(tree, shown, 1, tree[1]);
    expect(ids(first)).toEqual(["q1", "a2", "q4", "a5"]);   // back to the first answer, with what followed it
    expect(ids(switchedTo(tree, first, 1, tree[2]))).toEqual(["q1", "a3"]);  // the second has no follow-up: it ends there
    expect(ids(branchFrom(tree, tree[3]))).toEqual(["q4", "a5"]);
  });

  it("the turns known take in what the server numbered since, and stay the same list when nothing is new", () => {
    expect(withShown(tree, [tree[0], tree[2]])).toBe(tree);  // the branch shown is made of what is known
    const asked = withShown(tree, [q(1, null), a(3, 1), q(6, 3), { ...a(7, 6), status: "stopped" }, { ...q(9, 7), seq: undefined }]);
    expect(asked.map((t) => t.seq)).toEqual([1, 2, 3, 4, 5, 6, 7]);  // a refused question isn't the server's
    expect(withShown(asked, [{ ...q(6, 3), parent: undefined }]).find((t) => t.seq === 6)?.parent).toBe(3);  // keeps what it followed
  });
});
