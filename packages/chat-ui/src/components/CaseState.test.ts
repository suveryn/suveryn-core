import { afterEach, describe, expect, it } from "vitest";
import type { Case } from "../api";
import { setLang, t } from "../i18n";
import { fateLabel, isDue, onDay } from "./CaseState";

const closed = (over: Partial<Case> = {}): Case => ({
  id: "c1", reference: "2026/0417", name: "Sale", type: "sale", subject: {}, access: "default", state: "closed",
  opened_at: "2026-01-10T09:00:00Z", closed_at: "2026-10-01T09:00:00Z", keep_until: "2027-04-01T09:00:00Z", keep: false,
  manager: "alice", created_by: "alice", updated_at: "2026-10-01T09:00:00Z", my_role: "manager", ...over,
});

afterEach(() => setLang("en"));

describe("a closed case's fate (cases stage 3, suveryn-tracker#10)", () => {
  it("is due when its deletion is within a month and it isn't kept", () => {
    const now = new Date("2027-03-10T12:00:00Z");
    expect(isDue(closed(), now)).toBe(true);
    expect(isDue(closed(), new Date("2027-02-10T12:00:00Z"))).toBe(false);
    expect(isDue(closed({ keep: true }), now)).toBe(false);
    expect(isDue(closed({ keep_until: null }), now)).toBe(false);
    expect(isDue(closed({ state: "open", closed_at: null }), now)).toBe(false);
    expect(isDue(closed({ keep_until: "2027-03-01T09:00:00Z" }), now)).toBe(true);  // overdue: still due
  });

  it("says what becomes of it, in the interface language", () => {
    const far = closed({ keep_until: "2099-04-01T09:00:00Z" });
    expect(fateLabel(far, t())).toBe(`deleted ${onDay("2099-04-01T09:00:00Z")}`);
    expect(fateLabel(closed({ keep: true }), t())).toBe("kept");
    expect(fateLabel(closed({ keep_until: null }), t())).toBe("kept until deleted");
    expect(fateLabel(closed({ keep_until: "2026-01-01T09:00:00Z" }), t())).toContain("due for deletion");
    setLang("nl");
    expect(fateLabel(closed({ keep_until: null }), t())).toBe("bewaard tot het wordt verwijderd");
    expect(onDay("2027-04-01T09:00:00Z")).toMatch(/apr/i);
  });
});
