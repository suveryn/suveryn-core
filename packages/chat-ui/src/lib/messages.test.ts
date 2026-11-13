/**
 * Messages are codes (suveryn-tracker#139; docs/design/messages.md): every code of the server's registry has words
 * in every language, and a code this screen doesn't know still gets a sentence in the reader's language.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TABLES_FOR_TESTS } from "../i18n";
import { generalMessage, messageText, problemOf } from "./messages";

const REGISTRY: { areas: string[]; codes: Record<string, { kind: string; params?: Record<string, { type: string }> }> } = JSON.parse(readFileSync(
  new URL("../../../harness/src/suveryn_harness/messages.json", import.meta.url), "utf8"));
const sample = (code: string) => Object.fromEntries(Object.entries(REGISTRY.codes[code].params ?? {})
  .map(([name, p]) => [name, p.type === "number" ? 7 : "7F3K-92QD"]));

describe("the server's codes, worded (suveryn-tracker#139)", () => {
  it("has words for every code, area and kind of the registry, in every language, and for no other", () => {
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      // every code but the web setup's, which its own screens word (src/setup/i18n; screens.test.ts)
      expect(Object.keys(m.messages).sort(), lang).toEqual(Object.keys(REGISTRY.codes).filter((c) => !c.startsWith("setup.")).sort());
      expect(Object.keys(m.messageAreas).sort(), lang).toEqual(REGISTRY.areas.filter((a) => a !== "setup").sort());
      expect(Object.keys(m.messageKinds).sort(), lang).toEqual(["internal", "refused", "unavailable", "warning"]);
      for (const [code, c] of Object.entries(REGISTRY.codes).filter(([code]) => !code.startsWith("setup."))) {
        for (const params of [sample(code), {}]) {  // with its parameters, and when an older server sends none
          const text = messageText({ kind: c.kind, code, params }, m);
          expect(text, `${lang} ${code}`).toBeTruthy();
          expect(text, `${lang} ${code}`).not.toMatch(/undefined|null|\[object/);
        }
      }
    }
  });

  it("gives an unplanned failure its reference", () => {
    const { en, nl } = TABLES_FOR_TESTS;
    expect(messageText({ kind: "internal", code: "system.internal", params: { ref: "7F3K-92QD" } }, nl)).toMatch(/referentie aan uw beheerder: 7F3K-92QD\.$/);
    expect(messageText({ kind: "internal", code: "system.internal" }, en)).not.toMatch(/reference/);
  });

  it("never shows a sentence with a gap: a code whose value wasn't given gets its words without it", () => {
    const { en } = TABLES_FOR_TESTS;
    expect(messageText({ kind: "refused", code: "upload.too_large", params: { max_mb: 100 } }, en)).toBe("The file is larger than 100 MB.");
    expect(messageText({ kind: "refused", code: "upload.too_large" }, en)).toBe(en.messagesBare["upload.too_large"]);
    expect(messageText({ kind: "refused", code: "upload.archive_too_many" }, en)).toBe(en.messageAreas.upload);  // no words without it: its area's
    expect(messageText({ kind: "refused", code: "request.too_many", params: { seconds: 1 } }, en)).toBe("Too many requests. Try again in 1 second.");
  });

  it("words a code it doesn't know by its area, else by its kind, never from the server's English", () => {
    const { nl, fr } = TABLES_FOR_TESTS;
    expect(messageText({ kind: "refused", code: "run.something_new" }, nl)).toBe(nl.messageAreas.run);
    expect(messageText({ kind: "unavailable", code: "run.something_new" }, nl)).toBe(nl.messageKinds.unavailable);  // an area's words say a refusal
    expect(messageText({ kind: "refused", code: "tomorrow.something" }, fr)).toBe(fr.messageKinds.refused);
    expect(messageText({ kind: "internal", code: "tomorrow.broke", params: { ref: "ABCD-2345" } }, fr)).toMatch(/ABCD-2345\.$/);
    expect(messageText({}, fr)).toBe(fr.messageKinds.refused);
  });

  it("takes the gateway's Problem Details, and gives any other answer its status's general code", () => {
    expect(problemOf(409, { type: "urn:suveryn:problem:run.already_going", kind: "refused", code: "run.already_going", params: { run: "r1" }, detail: "English" }))
      .toEqual({ kind: "refused", code: "run.already_going", params: { run: "r1" } });
    expect(problemOf(502, "<html>Bad Gateway</html>")).toEqual(generalMessage(502));
    expect([401, 403, 404, 409, 413, 415, 422, 429, 500, 503].map((s) => generalMessage(s).code)).toEqual(["auth.signed_out", "request.forbidden",
      "request.not_found", "request.conflict", "request.too_large", "request.unsupported", "request.invalid", "request.too_many", "system.internal",
      "system.unavailable"]);
  });
});
