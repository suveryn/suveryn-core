import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearDraft, keepDraft, readDraft } from "./draft";

describe("the question being typed", () => {
  beforeEach(() => {
    const items = new Map<string, string>();
    vi.stubGlobal("sessionStorage", { getItem: (k: string) => items.get(k) ?? null,
      setItem: (k: string, v: string) => { items.set(k, v); }, removeItem: (k: string) => { items.delete(k); } });
  });

  it("is kept for the tab until it is emptied, sent or the person signs out", () => {
    expect(readDraft()).toBe("");
    keepDraft("What is the price?");
    expect(readDraft()).toBe("What is the price?");
    keepDraft("   ");
    expect(readDraft()).toBe("");
    keepDraft("Who signs?");
    clearDraft();
    expect(readDraft()).toBe("");
  });

  it("does without storage", () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("sessionStorage", { getItem: blocked, setItem: blocked, removeItem: blocked });
    keepDraft("x");
    expect(readDraft()).toBe("");
  });
});
