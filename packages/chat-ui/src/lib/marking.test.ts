/**
 * Source marking's regression set (suveryn-tracker#25): every reported case, and a case for each known gap, where the
 * source card must mark exactly the expected text. Fictional text only.
 */
import { describe, expect, it } from "vitest";
import { answerSentences, claimTerms, claimTexts, markerClaims, markPassage, markTerms, sentenceRanges, supportingRanges, termsOf, toBlocks, type PassagePart } from "./answer";
import { facts, numberValue, wordValue } from "./facts";

/** The marked runs of a passage: consecutive marked parts joined. */
const runs = (parts: PassagePart[]) => parts.reduce<string[]>((acc, p, i) => {
  if (!p.mark) return acc;
  if (i > 0 && parts[i - 1].mark) acc[acc.length - 1] += p.text; else acc.push(p.text);
  return acc;
}, []);
const strong = (parts: PassagePart[]) => parts.filter((p) => p.mark === "term").map((p) => p.text);
/** What the source card marks for the answer's first marker (one source). */
const card = (answer: string, passage: string) => {
  const { claim } = markerClaims(answer, 1)[0];
  return markPassage(passage, [claim], termsOf(claim));
};

describe("reported cases", () => {
  it("collects per source the figures, years, dates and names of the claims that cite it", () => {
    const text = "In de akte staan twee jaartallen:\n*   **1989** [3]\n*   **1996** [3]\n\nDe koper Jan Peeters betaalt EUR 1.275.000,00 op 12/03/2021 [1][2].";
    const terms = claimTerms(text, 3);
    expect(terms.get(3)).toEqual(["1989", "1996"]);
    expect(terms.get(1)).toEqual(["1.275.000,00", "12/03/2021"]);  // a claim with figures: the figures only
    expect(terms.get(2)).toEqual(terms.get(1));
    expect(claimTerms("Zie [9].", 3).size).toBe(0);  // a marker past the citations names nothing
    // reported: asked for years, "Europese" was marked too
    expect(claimTerms("De Europese richtlijn dateert van 2014 [4].", 4).get(4)).toEqual(["2014"]);
    expect(claimTerms("De koper is Jan Peeters [1].", 1).get(1)).toEqual(["Jan Peeters"]);  // no figures: the name
  });

  it("marks a whole name with its particles, also split over two lines (reported: Eric Van de Plas)", () => {
    const terms = claimTerms("De zaakvoerder is Eric Van de Plas [2]. Eric Van de Plas tekent [2].", 2).get(2)!;
    expect(terms).toEqual(["Eric Van de Plas", "Van de Plas"]);  // the second sentence starts with it: also without its first word
    const marked = (p: string) => markTerms(p, terms).filter((x) => x.mark).map((x) => x.text);
    expect(marked("Benoemd: de heer Eric Van de Plas, zaakvoerder.")).toEqual(["Eric Van de Plas"]);
    expect(marked("de heer Eric Van de\nPlas, wonende te Gent")).toEqual(["Eric Van de\nPlas"]);
    const witnesses = claimTerms("Notaris Charlotte d'Hondt en Pierre du Pont getuigen [1].", 1).get(1)!;
    expect(witnesses).toEqual(["Notaris Charlotte d'Hondt", "Charlotte d'Hondt", "Pierre du Pont"]);
    // the source writes the title elsewhere: the name is still marked whole
    expect(markTerms("mr. Charlotte d'Hondt, notaris, en Pierre du Pont", witnesses).filter((x) => x.mark).map((x) => x.text))
      .toEqual(["Charlotte d'Hondt", "Pierre du Pont"]);
  });

  it("marks the sentence a claim rests on, with all its numbers (reported: only years were marked)", () => {
    const answer = "De opzegtermijn bedraagt 12 weken [1]. De huurprijs is EUR 1.250,00 per maand [1].";
    const claims = claimTexts(answer, 1).get(1)!;
    expect(claims).toEqual(["De opzegtermijn bedraagt 12 weken", "De huurprijs is EUR 1.250,00 per maand"]);
    const passage = "Artikel 4. Duur. De huur loopt negen jaar. Artikel 5. Opzegging. Elke partij kan opzeggen met een termijn van 12 weken, " +
      "per aangetekende brief. Artikel 6. Huurprijs. De maandelijkse huurprijs bedraagt 1 250 euro, te betalen voor de vijfde.";
    const parts = markPassage(passage, claims, claimTerms(answer, 1).get(1)!);
    const sentences = parts.reduce<string[]>((acc, p, i) => {
      if (!p.mark) return acc;
      if (i > 0 && parts[i - 1].mark) acc[acc.length - 1] += p.text; else acc.push(p.text);
      return acc;
    }, []);
    expect(sentences).toEqual(["Elke partij kan opzeggen met een termijn van 12 weken, per aangetekende brief.",
      "De maandelijkse huurprijs bedraagt 1 250 euro, te betalen voor de vijfde."]);
    expect(parts.filter((p) => p.mark === "term").map((p) => p.text)).toEqual(["12", "1 250"]);  // the numbers in their sentences, in any form
    expect(supportingRanges("Een zin die er niets mee te maken heeft.", claims)).toEqual([]);  // no sentence: nothing marked
    // a sentence running on from a garbled first line (text in an upside-down figure): the line isn't marked
    const garbled = "(uesozoeysjeerdsuom — sBuinebwo) enuabe oyosish12\nElke partij kan opzeggen met een termijn van 12 weken.";
    const [[from, to]] = supportingRanges(garbled, claims);
    expect(garbled.slice(from, to)).toBe("Elke partij kan opzeggen met een termijn van 12 weken.");
  });

  it("shows what the clicked marker's claim rests on, not every claim citing the source (reported: a table of rows)", () => {
    const answer = "| Nr | Vak | Bron |\n| --- | --- | --- |\n| 3 | Functie van het slachtoffer | [1] |\n" +
      "| 12 | Datum werkhervatting na ongeval | [1] |\n\nZie ook [2].";
    const markers = markerClaims(answer, 2);
    // numbered as toBlocks numbers the markers (Segment.occ)
    const occ = toBlocks(answer, 2).flatMap((b) => (b.kind === "table" ? b.rows.flat(2) : b.segments)).filter((x) => x.kind === "cite");
    expect(occ.map((x) => (x.kind === "cite" ? [x.n, x.occ] : null))).toEqual([[1, 0], [1, 1], [2, 2]]);
    expect(markers.map((x) => x.n)).toEqual([1, 1, 2]);
    const passage = "Vak 3 vermeldt de functie van het slachtoffer. Vak 12 vermeldt de datum van werkhervatting na het ongeval.";
    const parts = markPassage(passage, [markers[1].claim], termsOf(markers[1].claim));
    expect(parts.filter((p) => p.mark).map((p) => p.text).join("")).toBe("Vak 12 vermeldt de datum van werkhervatting na het ongeval.");
    // a form's legend, numbered parts within a line and a table header after it (as reported): only part 12
    const legend = "9) wijze waarop ongeval gebeurde\n(8 + 9 omschrijft het gevaar) 12) datum werkhervatting na ongeval\n" +
      "4) Beroepscategorie 10) aard van het letsel\nNr. | Naam | Datum | Plaats | Datum\n(1) (2) (12) (13)";
    const legendMarks = markPassage(legend, [markers[1].claim], termsOf(markers[1].claim)).filter((p) => p.mark).map((p) => p.text);
    expect(legendMarks.join("")).toBe("12) datum werkhervatting na ongeval");
    // reported: "(module 1)" is a reference in a sentence, not a numbered part; the whole sentence, with its 1
    const prose = "Dit kan door indicatoren op te volgen (module 22).\nOok kan de audit (module 1) jaarlijks een update krijgen.";
    const audit = markPassage(prose, ["| 1 | Module 1 (audit update) |"], termsOf("| 1 | Module 1 (audit update) |")).filter((p) => p.mark);
    expect(audit.map((p) => p.text).join("")).toBe("Ook kan de audit (module 1) jaarlijks een update krijgen.");
    expect(audit.filter((p) => p.mark === "term").map((p) => p.text)).toEqual(["1"]);
    // an amount grouped with hard spaces is one number; two numbers with a plain space between are two
    const amounts = "De prijs bedraagt 1\u00a0275\u00a0000 euro.\nIn 2021 werden 12 kavels verkocht.";
    expect(markPassage(amounts, ["De prijs is 1.275.000"], []).filter((p) => p.mark).map((p) => p.text).join(""))
      .toBe("De prijs bedraagt 1\u00a0275\u00a0000 euro.");
    expect(markPassage(amounts, ["Er werden 12 kavels verkocht"], []).filter((p) => p.mark === "term").map((p) => p.text)).toEqual(["12"]);
  });

  it("marks those facts in the passage, whole only, and nothing else", () => {
    const passage = "Opgericht in 1989, gewijzigd in 1996. Nummer 119890 en 19896 blijven ongemoeid.";
    expect(markTerms(passage, ["1989", "1996"]).filter((p) => p.mark).map((p) => p.text)).toEqual(["1989", "1996"]);
    expect(markTerms(passage, []).length).toBe(1);
    expect(markTerms("de heer jan peeters", ["Peeters"]).filter((p) => p.mark).map((p) => p.text)).toEqual(["peeters"]);
  });
});


describe("sentences (suveryn-tracker#25)", () => {
  it("doesn't end a sentence at an abbreviation or an initial", () => {
    expect(markerClaims("Under art. 3 the seller bears the costs of the survey [1].", 1)[0].claim)
      .toBe("Under art. 3 the seller bears the costs of the survey");
    expect(answerSentences("See no. 4 and p. 12 of the annex. J. Smith signed it.")).toEqual(["See no. 4 and p. 12 of the annex.", "J. Smith signed it."]);
    const passage = "Art. 2. The buyer pays the price. Under art. 3 the seller bears the costs of the survey, as set out in no. 4 " +
      "of the annex. Art. 4. Other costs are shared.";
    const parts = card("Under art. 3 the seller bears the costs of the survey [1].", passage);
    expect(runs(parts)).toEqual(["Under art. 3 the seller bears the costs of the survey, as set out in no. 4 of the annex."]);
    expect(strong(parts)).toEqual(["3"]);
  });

  it("joins a word hyphenated over two lines, and keeps its lines together", () => {
    const passage = "Return to work is planned. Full resump-\ntion of work followed in spring.";
    expect(runs(card("The resumption of work [1].", passage))).toEqual(["Full resump-\ntion of work followed in spring."]);
  });

  it("takes a table row as a sentence of its own", () => {
    const table = "Costs of the sale\n| Item | Amount |\n| --- | --- |\n| Deposit | 25,000 |\n| Price | 250,000 |";
    expect(sentenceRanges(table).map(([a, z]) => table.slice(a, z))).toEqual(
      ["Costs of the sale", "| Item | Amount |", "| --- | --- |", "| Deposit | 25,000 |", "| Price | 250,000 |"]);
    const parts = card("The deposit is 25 000 euro [1].", table);
    expect(runs(parts)).toEqual(["| Deposit | 25,000 |"]);
    expect(strong(parts)).toEqual(["25,000"]);
    const fields = "Deposit\t25,000\nPrice\t250,000";
    expect(runs(card("The price is 250 000 euro [1].", fields))).toEqual(["Price\t250,000"]);
  });

  it("marks every sentence a claim rests on, and no sentence sharing a word or two", () => {
    const passage = "The tenant may terminate the lease at any time. Notice of three months applies, sent by registered letter. " +
      "The landlord keeps the deposit for the tenant.";
    expect(runs(card("The tenant may terminate with three months' notice by registered letter [1].", passage))).toEqual([
      "The tenant may terminate the lease at any time.", "Notice of three months applies, sent by registered letter."]);
  });
});

describe("facts in another form (suveryn-tracker#25)", () => {
  it("reads numbers with any separators, amounts with a scale word, and number words", () => {
    expect([numberValue("1.275.000,00"), numberValue("1 275 000"), numberValue("1,250.50"), numberValue("1,2"), numberValue("0,125")])
      .toEqual([1275000, 1275000, 1250.5, 1.2, 0.125]);
    const values = (text: string) => facts(text).map((f) => f.values[0]);
    expect(values("€ 1,2 million, EUR 1.200.000,00, 1.2 mio and two million")).toEqual(["n:1200000", "n:1200000", "n:1200000", "n:2000000"]);
    // the tables of number words (Dutch, French, English)
    expect(["twaalf", "één", "eenentwintig", "tweeëntwintig", "douze", "vingt-deux", "vingt et un", "quatre-vingt-dix",
      "soixante-dix-sept", "septante", "twelve", "twenty-one"].map((w) => wordValue(w)))
      .toEqual([12, 1, 21, 22, 12, 22, 21, 90, 77, 70, 12, 21]);
    // articles and other words are no numbers
    expect(["een", "un", "one", "self-employed", "deux-trois"].map((w) => wordValue(w))).toEqual([null, null, null, null, null]);
    expect(values("They took it in acht and paid two")).toEqual(["n:2"]);
  });

  it("reads dates in numeric and written forms as one date", () => {
    const day = (text: string) => facts(text)[0]?.values[0];
    for (const text of ["12/03/2021", "12-03-2021", "12.03.2021", "12/03/21", "2021-03-12", "12 March 2021", "March 12, 2021",
      "12 maart 2021", "12 mars 2021", "12th March 2021"]) expect(day(text), text).toBe("d:2021-03-12");
    expect(day("1er mars 2021")).toBe("d:2021-03-01");
    expect(facts("13/13/2021").map((f) => f.values[0])).toEqual(["n:13", "n:13", "n:2021"]);  // no month 13: numbers
  });

  it("marks a fact the source writes otherwise: a number word, a date, an amount", () => {
    const notice = card("The notice period is twelve weeks [1].",
      "The lease runs nine years. Either party may give notice of 12 weeks by registered letter.");
    expect(runs(notice)).toEqual(["Either party may give notice of 12 weeks by registered letter."]);
    expect(strong(notice)).toEqual(["12"]);
    const deed = card("The deed was signed on 12 March 2021 [1].",
      "The deed was executed on 12/03/2021 before the notary. The price was paid on 15/04/2022.");
    expect(runs(deed)).toEqual(["The deed was executed on 12/03/2021 before the notary."]);
    expect(strong(deed)).toEqual(["12/03/2021"]);
    const price = card("The price is € 1.2 million [1].", "The parties agree. The price amounts to EUR 1.200.000,00, paid at signing.");
    expect(runs(price)).toEqual(["The price amounts to EUR 1.200.000,00, paid at signing."]);
    expect(strong(price)).toEqual(["1.200.000,00"]);
    // a claim's date anywhere in the passage, also in another form
    expect(strong(markPassage("Signed: 12 March 2021.", [], termsOf("signed on 12/03/2021")))).toEqual(["12 March 2021"]);
  });

  it("marks a name in curly quotes", () => {
    const parts = card("The seller is ‘Harbour Builders’ [1].", "Between the company “Harbour Builders” of Ghent and the buyer.");
    expect(strong(parts)).toEqual(["Harbour Builders"]);
  });

  // Step 3 of suveryn-tracker#25: by meaning, with the embedding model on the server.
  it.todo("marks a paraphrase: the answer's \"employer\" where the source says \"undertaking\"");
  it.todo("marks a French source for a Dutch answer");
});
