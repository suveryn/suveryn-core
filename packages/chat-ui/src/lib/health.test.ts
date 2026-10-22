import { describe, expect, it } from "vitest";
import type { Health } from "../api";
import { databaseDown } from "./health";

const health = (history: string, cases?: string): Health => ({
  status: "ok", backend: { reachable: true, status: "ok", model: null }, documents: { status: "ready", detail: null },
  auth: { status: "ready", detail: null }, history: { status: history, detail: null },
  ...(cases ? { cases: { status: cases, detail: null } } : {}),
} as Health);

describe("the database, as /health tells it", () => {
  it("is down when a store in it says failed", () => {
    expect(databaseDown(health("failed", "failed"))).toBe(true);
    expect(databaseDown(health("ready", "failed"))).toBe(true);
  });
  it("is not down when ready, absent, or when the server didn't answer at all", () => {
    expect(databaseDown(health("ready", "ready"))).toBe(false);
    expect(databaseDown(health("unavailable"))).toBe(false);
    expect(databaseDown(null)).toBe(false);
  });
});
