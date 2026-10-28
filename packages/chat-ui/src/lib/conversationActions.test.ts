import { describe, expect, it } from "vitest";
import type { Case, ConversationSummary } from "../api";
import { conversationActions, moveTargets, pinnedConversations } from "./conversationActions";

const conv = (over: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id: "c1", title: "Sale", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z", owner: "alice", ...over,
});
const kase = (over: Partial<Case> = {}): Case => ({
  id: "k1", reference: "2026/0417", name: "Sale", type: "sale", subject: {}, access: "default", state: "open",
  opened_at: "", closed_at: null, keep_until: null, keep: false, manager: "alice", created_by: "alice", updated_at: "",
  my_role: "contributor", ...over,
});
const offered = (c: ConversationSummary, me = "alice", withOpen = false) =>
  conversationActions(c, me, withOpen).map((a) => `${a.id}${a.disabled ? "-" : ""}${a.reason ? `(${a.reason})` : ""}`);

describe("a conversation's menu (docs/design/chat-ui.md §3 and §4)", () => {
  it("offers everything for one's own personal conversation", () => {
    expect(offered(conv())).toEqual(["pin", "rename", "move", "delete"]);
    expect(offered(conv({ pinned: true }), "alice", true)).toEqual(["open", "unpin", "rename", "move", "delete"]);
  });

  it("lets a conversation in a case follow its case: no pin, no move", () => {
    expect(offered(conv({ case_id: "k1" }))).toEqual(["pin-(followsCase)", "rename", "move-", "delete"]);
  });

  it("shows a colleague's shared conversation's actions disabled", () => {
    expect(offered(conv({ case_id: "k1", shared: true, owner: "bob" }))).toEqual(["pin-(followsCase)", "rename-", "move-", "delete-"]);
  });

  it("pins only personal conversations in the column", () => {
    const list = [conv({ id: "a", pinned: true }), conv({ id: "b" }), conv({ id: "c", pinned: true, case_id: "k1" })];
    expect(pinnedConversations(list).map((c) => c.id)).toEqual(["a"]);
  });

  it("moves only into open cases the person contributes to, by reference", () => {
    const cases = [kase({ id: "b", reference: "2026/0420" }), kase({ id: "a", reference: "2026/0418", my_role: "manager" }),
      kase({ id: "r", my_role: "reader" }), kase({ id: "x", state: "closed" }), kase({ id: "n", my_role: null })];
    expect(moveTargets(cases).map((c) => c.id)).toEqual(["a", "b"]);
  });
});
