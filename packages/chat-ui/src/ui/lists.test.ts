import { describe, expect, it } from "vitest";
import { lateSuggestions } from "./lists";

const arriving = { changed: true, empty: false, waiting: false, focused: true, open: false, typed: "Koen", chosen: false };

describe("suggestions that arrive after the last keystroke (the member search, e2e walk-through)", () => {
  it("open the list while the person is in the field with something typed", () => {
    expect(lateSuggestions(arriving)).toEqual({ open: true, waiting: true });
  });

  it("keep asking on the next renders, until React Aria has them and the list is open", () => {
    const later = { ...arriving, changed: false, waiting: true };
    expect(lateSuggestions(later)).toEqual({ open: true, waiting: true });             // not open yet: ask again
    expect(lateSuggestions({ ...later, open: true })).toEqual({ open: false, waiting: false });  // open: done
    expect(lateSuggestions({ ...later, waiting: false })).toEqual({ open: false, waiting: false }); // nothing new arrived
  });

  it("stop waiting when the person leaves the field, and never open on none", () => {
    expect(lateSuggestions({ ...arriving, focused: false })).toEqual({ open: false, waiting: false });
    expect(lateSuggestions({ ...arriving, empty: true })).toEqual({ open: false, waiting: false });
  });

  it("don't open with nothing typed or a suggestion already chosen, but stay ready for the next keystroke", () => {
    expect(lateSuggestions({ ...arriving, typed: "  " })).toEqual({ open: false, waiting: true });
    expect(lateSuggestions({ ...arriving, chosen: true })).toEqual({ open: false, waiting: true });
  });
});
