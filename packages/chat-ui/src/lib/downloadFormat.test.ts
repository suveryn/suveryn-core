import { beforeEach, describe, expect, it, vi } from "vitest";

/** The browser's storage, in memory (the tests run in Node). */
function fakeStorage() {
  const items = new Map<string, string>();
  return { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => { items.set(k, v); }, clear: () => items.clear() };
}

describe("the default download format", () => {
  let localStorage: ReturnType<typeof fakeStorage>;
  beforeEach(() => { vi.resetModules(); localStorage = fakeStorage(); vi.stubGlobal("localStorage", localStorage); });

  it("is Word and Excel at first, then the last one chosen, per kind", async () => {
    const { readFormat, rememberFormat } = await import("./downloadFormat");
    expect([readFormat("answer"), readFormat("table")]).toEqual(["docx", "xlsx"]);
    rememberFormat("table", "csv");
    expect([readFormat("answer"), readFormat("table")]).toEqual(["docx", "csv"]);
    expect(localStorage.getItem("suveryn.format.table")).toBe("csv");
  });

  it("is read back after a reload, and an unknown value is ignored", async () => {
    localStorage.setItem("suveryn.format.answer", "md");
    localStorage.setItem("suveryn.format.table", "pdf");
    const { readFormat } = await import("./downloadFormat");
    expect([readFormat("answer"), readFormat("table")]).toEqual(["md", "xlsx"]);
  });

  it("still works for this page when the browser keeps nothing", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    const { readFormat, rememberFormat } = await import("./downloadFormat");
    expect(readFormat("answer")).toBe("docx");
    rememberFormat("answer", "md");
    expect(readFormat("answer")).toBe("md");
  });
});
