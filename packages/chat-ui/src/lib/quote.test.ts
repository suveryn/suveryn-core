import { describe, expect, it } from "vitest";
import { citedContext, quoteFor } from "./quote";

const DEED = [
  "Artikel 1. De verkoper verkoopt aan de koper, die aanvaardt, het hierna beschreven goed.",
  "Artikel 2. De prijs bedraagt vierhonderdtwaalfduizend vijfhonderd euro, waarvan een voorschot van tien procent.",
  "Artikel 3. De authentieke akte wordt verleden uiterlijk vier maanden na de vervulling van de opschortende voorwaarde.",
  "Artikel 4. Het goed wordt verkocht in de staat waarin het zich bevindt, zonder waarborg voor zichtbare gebreken.",
].join(" ");

describe("the quote on a Check card (VM regression 9c97d76, finding 7)", () => {
  it("is the sentence the value comes from, not the whole passage", () => {
    expect(quoteFor(DEED, "uiterlijk vier maanden na de opschortende voorwaarde"))
      .toBe("… Artikel 3. De authentieke akte wordt verleden uiterlijk vier maanden na de vervulling van de opschortende voorwaarde. …");
    expect(quoteFor(DEED, "verkoper verkoopt")).toMatch(/^Artikel 1\..* …$/);
  });

  it("keeps a short passage whole, and the whole passage when nothing matches", () => {
    expect(quoteFor("De prijs bedraagt EUR 412.500,00.", "EUR 415.000,00")).toBe("De prijs bedraagt EUR 412.500,00.");
    expect(quoteFor(DEED, "xyz")).toBe(DEED);
  });
});


describe("the cited words in their context (board P02)", () => {
  it("shows the cited words, a few words after, and … where the passage goes on", () => {
    const c = citedContext(DEED, "uiterlijk vier maanden na de vervulling");
    expect(c.before).toBe("… ");
    expect(c.cited).toBe("uiterlijk vier maanden na de vervulling");
    expect(c.after).toBe(" van de opschortende voorwaarde. …");
  });
  it("quotes the closest sentence when the words aren't in the passage as written", () => {
    expect(citedContext(DEED, "EUR 412.500").cited).toBeUndefined();
  });
});
