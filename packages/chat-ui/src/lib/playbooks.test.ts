import { describe, expect, it } from "vitest";
import { entryPath, factLabel, nextEntry, shownFacts, splitPath, stepQuestion } from "./playbooks";

const words = { title: "Formation", summary: "", labels: { founders: "Founder(s)", "founders.name": "Name", conditions: "Conditions", price: "Price" },
                questions: { missing: "The documents don't mention {label}." } };

describe("paths into a list (format 3)", () => {
  it("takes a fact id apart", () => {
    expect(splitPath("price")).toEqual({ root: "price", index: null, field: null });
    expect(splitPath("founders[2].name")).toEqual({ root: "founders", index: 2, field: "name" });
    expect(splitPath("conditions[1]")).toEqual({ root: "conditions", index: 1, field: null });
    expect(splitPath("Founders[1]")).toEqual({ root: "Founders[1]", index: null, field: null });
    expect(entryPath("founders", 3, "name")).toBe("founders[3].name");
    expect(entryPath("conditions", 1)).toBe("conditions[1]");
  });
  it("labels an entry's value by the list, the number and the field", () => {
    expect(factLabel(words, "price")).toBe("Price");
    expect(factLabel(words, "founders[2].name")).toBe("Founder(s) 2 · Name");
    expect(factLabel(words, "founders[2].age")).toBe("Founder(s) 2 · age");
    expect(factLabel(words, "conditions[1]")).toBe("Conditions 1");
    expect(factLabel(words, "nobody")).toBe("nobody");
    expect(stepQuestion(words, "missing", "founders[1].name")).toBe("The documents don't mention Founder(s) 1 · Name.");
  });
  it("hides a list behind its entries and numbers the next one", () => {
    const facts = [{ id: "founders" }, { id: "founders[1].name" }, { id: "founders[3].name" }, { id: "conditions" }];
    expect(shownFacts(facts).map((f) => f.id)).toEqual(["founders[1].name", "founders[3].name", "conditions"]);
    expect(nextEntry(facts, "founders")).toBe(4);
    expect(nextEntry(facts, "conditions")).toBe(1);
  });
});
