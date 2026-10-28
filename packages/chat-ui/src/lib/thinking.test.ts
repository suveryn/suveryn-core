import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Turn } from "../types";
import { conversationHistory } from "./history";
import { statusText } from "./status";

function fakeStorage() {
  const items = new Map<string, string>();
  return { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => { items.set(k, v); } };
}

const question: Turn = { id: "q", role: "user", text: "What is the price?", attachments: [] };
const answer = (over = {}): Turn => ({ id: "a", role: "assistant", text: "EUR 1 [1].", citations: [], status: "done", grounded: true, ...over });

describe("Fast or Thorough (docs/design/chat-ui.md §5)", () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal("localStorage", fakeStorage()); });

  it("starts Fast, then keeps the default chosen under Settings in this browser", async () => {
    const { setThinkingDefault, thinkingDefault } = await import("./thinking");
    expect(thinkingDefault()).toBe(false);
    setThinkingDefault(true);
    expect(thinkingDefault()).toBe(true);
  });

  it("without storage, keeps the default for this page", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    const { setThinkingDefault, thinkingDefault } = await import("./thinking");
    expect(thinkingDefault()).toBe(false);
    setThinkingDefault(true);
    expect(thinkingDefault()).toBe(true);
  });

  it("goes on in a reopened conversation as its last answer was asked", async () => {
    const { restoreThinking } = await import("./thinking");
    expect(restoreThinking([question, answer({ thinking: true })], false)).toBe(true);
    expect(restoreThinking([question, answer({ thinking: true }), question, answer()], true)).toBe(true);  // older answers: no field
    expect(restoreThinking([question, answer()], false)).toBe(false);
    expect(restoreThinking([], true)).toBe(true);
  });

  it("says how long the model thought", async () => {
    const { thoughtTime } = await import("./thinking");
    expect([thoughtTime(0.2), thoughtTime(14.4), thoughtTime(60), thoughtTime(65)]).toEqual(["1 s", "14 s", "1 min", "1 min 5 s"]);
  });

  it("never sends the reasoning back to the model with the next question", () => {
    const history = conversationHistory([question, answer({ thinking: true, reasoning: "The deed says …", thoughtSeconds: 9 })]);
    expect(history).toEqual([{ role: "user", content: "What is the price?" }, { role: "assistant", content: "EUR 1 [1]." }]);
  });

  it("says the model is thinking while it does", () => {
    expect(statusText({ step: "thinking", passages: null, complete: null, model: null })).toBeTruthy();
  });
});
