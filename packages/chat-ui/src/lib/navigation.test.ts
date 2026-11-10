import { describe, expect, it } from "vitest";
import type { ConversationSummary, PlaybookInfo, Run, RunSummary } from "../api";
import type { AssistantTurn, Turn, UserTurn } from "../types";
import { PIN_HINT_AFTER } from "./conversationActions";
import { asksBeforeSignOut, inAnotherPlace, liveRunInstead, memberName, needsCaseOpen, pinHintDue, reopened, runIsLive,
         runPlaybook } from "./navigation";

describe("places (App.tsx, now lib/navigation.ts)", () => {
  it("something listed elsewhere is in another place unless it is in the open one", () => {
    expect(inAnotherPlace("case-1", "case-1")).toBe(false);
    expect(inAnotherPlace(null, null)).toBe(false);
    expect(inAnotherPlace(undefined, null)).toBe(false);        // personal: no case id
    expect(inAnotherPlace("case-1", null)).toBe(true);
    expect(inAnotherPlace(null, "case-1")).toBe(true);
    expect(inAnotherPlace("case-2", "case-1")).toBe(true);
  });

  it("the case menu opens the case behind its members, its log and closing it, not to open or unpin it", () => {
    expect(["open", "unpin", "members", "log", "close"].filter((a) => needsCaseOpen(a as never))).toEqual(["members", "log", "close"]);
  });
});

describe("playbook runs", () => {
  const run = (extra: Partial<Run>) => ({ playbook_id: "pb/deed-intake", status: "waiting", ...extra }) as Run;

  it("show the playbook they started under, whatever is installed now", () => {
    const own = { id: "pb/deed-intake", version: "1.1" } as PlaybookInfo;
    expect(runPlaybook(run({ playbook: own }))).toBe(own);
    expect(runPlaybook(null)).toBeNull();
  });

  it("are live while reading, waiting or paused", () => {
    expect(["reading", "waiting", "paused", "done", "cancelled", "failed"].filter((s) => runIsLive({ status: s } as Run)))
      .toEqual(["reading", "waiting", "paused"]);
    expect(runIsLive(null)).toBe(false);
  });

  it("a second start in a case (409) opens the live run instead; other refusals don't", () => {
    const live = { id: "r1" } as RunSummary;
    expect(liveRunInstead(409, { "case-1": live }, "case-1")).toBe(live);
    expect(liveRunInstead(409, { "case-2": live }, "case-1")).toBeNull();   // live elsewhere only
    expect(liveRunInstead(409, null, "case-1")).toBeNull();                 // the live runs couldn't be read
    expect(liveRunInstead(403, { "case-1": live }, "case-1")).toBeNull();
  });

  it("name people as the case knows them, or by username", () => {
    const members = [{ username: "koen", name: "Koen Collega" }, { username: "nameless", name: "" }];
    expect(memberName(members, "koen")).toBe("Koen Collega");
    expect(memberName(members, "nameless")).toBe("nameless");
    expect(memberName(members, "stranger")).toBe("stranger");
  });
});

describe("conversations", () => {
  const personal = (id: string, pinned = true) => ({ id, pinned, case_id: null }) as unknown as ConversationSummary;
  const pinned = (n: number) => Array.from({ length: n }, (_, i) => personal(`c${i}`));

  it("pinning past the limit says once that a case keeps them together", () => {
    expect(pinHintDue(pinned(PIN_HINT_AFTER), "new", true, false)).toBe(true);
    expect(pinHintDue(pinned(PIN_HINT_AFTER - 1), "new", true, false)).toBe(false);
    expect(pinHintDue(pinned(PIN_HINT_AFTER), "new", true, true)).toBe(false);    // said before
    expect(pinHintDue(pinned(PIN_HINT_AFTER), "new", false, false)).toBe(false);  // unpinning
    expect(pinHintDue(pinned(PIN_HINT_AFTER), "c0", true, false)).toBe(false);    // already counted
    const inCases = pinned(PIN_HINT_AFTER).map((c) => ({ ...c, case_id: "case-1" }));
    expect(pinHintDue(inCases, "new", true, false)).toBe(false);                  // a case's don't count
  });

  it("reopened: with its Ask about choice, Fast or Thorough, and the saved form to compare with", () => {
    const question: UserTurn = { id: "u", role: "user", text: "Wat is de prijs?", attachments: [],
                                 about: [{ documentId: "d1", filename: "akte.pdf" }] };
    const answer: AssistantTurn = { id: "a", role: "assistant", text: "EUR 1.275.000,00", citations: [], status: "done", grounded: true, thinking: true };
    const r = reopened([question, answer] as Turn[], false);
    expect(r.about).toEqual([{ documentId: "d1", filename: "akte.pdf" }]);
    expect(r.thinking).toBe(true);
    expect(r.turns.map((t) => t.id)).toEqual(["u", "a"]);
    expect(JSON.parse(r.lastSaved).map((t: Turn) => t.id)).toEqual(["u", "a"]);
    expect(reopened([], false)).toMatchObject({ turns: [], about: [], thinking: false });
  });

  it("signing out asks first only when there are saved conversations to keep", () => {
    expect(asksBeforeSignOut(true, 3)).toBe(true);
    expect(asksBeforeSignOut(true, 0)).toBe(false);
    expect(asksBeforeSignOut(false, 3)).toBe(false);
  });
});
