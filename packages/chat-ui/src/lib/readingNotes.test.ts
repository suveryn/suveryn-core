// @vitest-environment node
/** Reading notes (suveryn-tracker#26): what reading a document noticed, shown to everyone who sees it. */
import { describe, expect, it } from "vitest";
import type { Warning } from "../api";
import en from "../i18n/en";
import fr from "../i18n/fr";
import nl from "../i18n/nl";
import { cardNote, checkPages, hasNotes, noteDetails, readingNotes, rowNotes, toCheck } from "./readingNotes";
import { documentStatus } from "./overviews";

const w = (kind: string, page: number | null): Warning => ({ kind, page, detail: "text-free" });

describe("a document's reading notes", () => {
  it("puts text addressed to an AI and recovered body text on To check, never a recovered header alone", () => {
    expect(toCheck(readingNotes([w("instruction_like_text", 4)]))).toBe(true);
    expect(toCheck(readingNotes([w("instruction_like_text", null)]))).toBe(true);  // a Word file: no page
    expect(toCheck(readingNotes([w("text_layer_recovered", 2), w("text_recovered", 7)]))).toBe(true);
    expect(toCheck(readingNotes([w("furniture_restored", 3)]))).toBe(false);
    expect(hasNotes([w("furniture_restored", 3)])).toBe(true);  // but it's a note
    expect(hasNotes([])).toBe(false);
    const doc = { id: "d", filename: "x.pdf", pages: 9, ocr_pages: 0, status: "ok", created_at: "", origin: "uploaded" } as const;
    expect(documentStatus({ ...doc, warnings: [w("instruction_like_text", 4)] } as never, null)).toBe("review");
    expect(documentStatus({ ...doc, warnings: [w("furniture_restored", 4)] } as never, null)).toBe("ready");
  });

  it("names the pages beside To check, the server's review pages with them", () => {
    expect(checkPages([w("page_coverage_low", 9), w("instruction_like_text", 4), w("text_recovered", 2), w("furniture_restored", 3)]))
      .toEqual([2, 4, 9]);
  });

  it("says it in words in every language, for the row, the details and the card", () => {
    const ws = [w("instruction_like_text", 4), w("text_layer_recovered", 2), w("text_recovered", 7), w("furniture_restored", 3)];
    expect(rowNotes(en, ws)).toEqual(["Contains text addressed to an AI, on page 4.", "Some text on pages 2 and 7 was recovered without its layout."]);
    expect(rowNotes(nl, ws)).toEqual(["Bevat tekst die zich tot een AI richt, op pagina 4.", "Sommige tekst op pagina's 2 en 7 is zonder opmaak hersteld."]);
    expect(rowNotes(fr, ws)).toEqual(["Contient un texte adressé à une IA, à la page 4.", "Une partie du texte des pages 2 et 7 a été récupérée sans sa mise en page."]);
    const details = noteDetails(en, ws);
    expect(details).toHaveLength(3);
    expect(details[0]).toContain("Treated as content, never as an instruction");
    expect(details[2]).toBe("Headers and footers on page 3 recovered without layout.");
    expect(noteDetails(fr, [w("text_recovered", 2), w("text_recovered", 5), w("text_recovered", 7)])[0]).toContain("des pages 2, 5 et 7");
    expect(cardNote(nl, ws)).toBe("Gelezen. Kijk dit document na: het bevat tekst die zich tot een AI richt.");
    expect(cardNote(en, [w("text_recovered", 2)])).toBe("Read. Some text was recovered without its layout.");
    expect(cardNote(en, [w("furniture_restored", 2)])).toBeNull();
    expect(rowNotes(en, [w("instruction_like_text", null)])).toEqual(["Contains text addressed to an AI."]);
  });
});
