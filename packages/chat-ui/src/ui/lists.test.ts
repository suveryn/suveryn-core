import { describe, expect, it } from "vitest";
import { opensOnArrival } from "./lists";

const base = { before: "", after: "u-koen", focused: true, open: false, typed: "Koen", chosen: false };

describe("suggestions that arrive after the last keystroke (the member search, e2e walk-through)", () => {
  it("open the list while the person is in the field with something typed", () => {
    expect(opensOnArrival(base)).toBe(true);
    expect(opensOnArrival({ ...base, before: "u-anna\nu-bert" })).toBe(true); // the directory's first answer, for fewer letters
  });

  it("leave it alone otherwise", () => {
    expect(opensOnArrival({ ...base, before: "u-koen" })).toBe(false);   // the same suggestions
    expect(opensOnArrival({ ...base, after: "" })).toBe(false);          // none
    expect(opensOnArrival({ ...base, focused: false })).toBe(false);     // the person has moved on
    expect(opensOnArrival({ ...base, open: true })).toBe(false);         // already open
    expect(opensOnArrival({ ...base, typed: "  " })).toBe(false);        // nothing typed
    expect(opensOnArrival({ ...base, chosen: true })).toBe(false);       // a suggestion already chosen
  });
});
