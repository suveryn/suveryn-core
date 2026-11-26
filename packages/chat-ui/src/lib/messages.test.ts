/**
 * Messages are codes (suveryn-tracker#139; docs/design/messages.md): every code of the server's registry has words
 * in every language, and a code this screen doesn't know still gets a sentence in the reader's language.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { TABLES_FOR_TESTS } from "../i18n";
import { Unreachable } from "./gateway";
import { afterRefresh, generalMessage, messageText, problemOf } from "./messages";

const REGISTRY: { areas: string[]; codes: Record<string, { kind: string; params?: Record<string, { type: string }> }> } = JSON.parse(readFileSync(
  new URL("../../../harness/src/suveryn_harness/messages.json", import.meta.url), "utf8"));
const sample = (code: string) => Object.fromEntries(Object.entries(REGISTRY.codes[code].params ?? {})
  .map(([name, p]) => [name, p.type === "number" ? 7 : "7F3K-92QD"]));

// the areas other screens word: the web setup's (src/setup/i18n; screens.test.ts) and the appliance's console's
// (suveryn-appliance's installer-text.json; suveryn-tracker#160)
const ELSEWHERE = ["setup", "network", "bundle"];
const here = (code: string) => !ELSEWHERE.includes(code.split(".")[0]);

describe("the server's codes, worded (suveryn-tracker#139)", () => {
  it("has words for every code, area and kind of the registry, in every language, and for no other", () => {
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      expect(Object.keys(m.messages).sort(), lang).toEqual(Object.keys(REGISTRY.codes).filter(here).sort());
      expect(Object.keys(m.messageAreas).sort(), lang).toEqual(REGISTRY.areas.filter((a) => !ELSEWHERE.includes(a)).sort());
      expect(Object.keys(m.messageKinds).sort(), lang).toEqual(["internal", "refused", "unavailable", "warning"]);
      for (const [code, c] of Object.entries(REGISTRY.codes).filter(([code]) => here(code))) {
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
    expect(messageText({ kind: "refused", code: "upload.archive_files_too_many" }, en)).toBe(en.messageAreas.upload);  // no words without it: its area's
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

// suveryn-tracker#272: a refresh the screen makes by itself never fails in silence. This refuses `.catch(() => {})`,
// `.catch(() => undefined)` and a catch whose comment trusts the connection check to explain a refusal; a refresh
// ends in Chat's `refreshFailed`, or in its dialog's own error line. Other empty catches (browser storage, a retry
// asked again next round) are not refused.
const SILENT = /\.catch\(\s*\(\)\s*=>\s*(\{\s*\}|undefined)\s*\)|catch\s*\{\s*\/\*[^*]*health check explains/;
const SRC = new URL("..", import.meta.url).pathname;
const sources = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  if (name === "node_modules" || name === "generated") return [];
  return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
});

describe("a failure", () => {
  it("is never swallowed in silence", () => {
    const silent = sources(SRC).flatMap((f) => readFileSync(f, "utf8").split("\n")
      .map((line, i) => [`${relative(SRC, f)}:${i + 1}`, line] as const))
      .filter(([, line]) => SILENT.test(line)).map(([where]) => where);
    expect(silent, "say it: App's refreshFailed, or the dialog's own error line").toEqual([]);
  });
});

describe("the line after a refresh", () => {
  const words = { refreshFailed: ({ why }: { why: string }) => `The screen couldn't be brought up to date. ${why}` };
  const refused = new Error("You can't see this case.");
  const said = words.refreshFailed({ why: refused.message });

  it("says a refusal, with the gateway's words", () => {
    expect(afterRefresh(null, null, refused, words)).toEqual({ shown: said, own: said });
  });
  it("leaves a gateway that can't be reached to the connection check", () => {
    expect(afterRefresh(null, null, new Unreachable("sūveryn can't be reached."), words)).toEqual({ shown: null, own: null });
  });
  it("says it once: a failure again, or another, leaves the line as it stands", () => {
    expect(afterRefresh(said, said, new Error("Something went wrong (7F3K-92QD)."), words)).toEqual({ shown: said, own: said });
    expect(afterRefresh("The case couldn't be pinned.", null, refused, words)).toEqual({ shown: "The case couldn't be pinned.", own: null });
  });
  it("goes away when a refresh works again, and only its own line", () => {
    expect(afterRefresh(said, said, null, words)).toEqual({ shown: null, own: null });
    expect(afterRefresh("The case couldn't be pinned.", said, null, words)).toEqual({ shown: "The case couldn't be pinned.", own: said });
  });
});

