/** The rules for calling generated code (src/generated; README, "The gateway's code (generated)"), held by the
 *  sources themselves, so they hold for every area that moves (suveryn-tracker#159). */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = new URL(".", import.meta.url).pathname;
const generated = readFileSync(join(SRC, "generated/gateway.ts"), "utf8");
// the code people wrote: not the generated file, not a test or its helpers, not the previews' stand-in gateway
const written = (readdirSync(SRC, { recursive: true }) as string[])
  .filter((f) => /\.tsx?$/.test(f) && !/(^|\/)(generated|test|preview)\//.test(f) && !/\.test\.tsx?$/.test(f))
  .map((f) => [f, readFileSync(join(SRC, f), "utf8")] as const);

// Generated and called by no screen's code, each for its reason. Taken out of here the day one is called.
const NOT_CALLED: Record<string, string> = {
  getUserPicture: "a picture is loaded by the page itself, as an image's address: the generated one (ui/avatar.tsx)",
  deleteUserPicture: "no screen removes someone else's picture yet",
  addRunDocuments: "no screen sends a document for a request the run has already had answered yet",
};
/** Whether hand-written `text` names the address `generated` code calls: at the start of a string, each part
 *  (`${caseId}`) whatever it is called there, and nothing more of an address after it; or the address up to its first
 *  part as a string of its own, to which the rest is added (`"/v1/cases/" + id`). A net, not a proof. */
function names(text: string, address: string): boolean {
  const escaped = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const literal = escaped(address).replace(/\\\$\\\{\w+\\\}/g, "\\$\\{[^}]*\\}");
  const start = address.includes("${") ? `|["'\`]${escaped(address.slice(0, address.indexOf("${")))}["'\`]` : "";
  return new RegExp(`["'\`]${literal}(?![\\w/-])${start}`).test(text);
}

describe("calling generated code", () => {
  it("an id put into an address is encoded by the caller: Orval puts it in as it is given", () => {
    // the generated calls whose address takes a part: `export const getClockRequest = async (rid: string, …`
    const withPart = [...generated.matchAll(/export const get(\w+)Url = \((\w+): string/g)]
      .map((m) => m[1][0].toLowerCase() + m[1].slice(1));
    expect(withPart).toContain("getClockRequest");
    for (const name of withPart) {
      // called as `gateway.<name>(`: the screens' own names for calls may be the same words (src/api.ts)
      const uses = written.flatMap(([file, text]) => [...text.matchAll(new RegExp(`\\bgateway\\.${name}\\(([^)]*)`, "g"))].map((m) => [file, m[1]] as const));
      if (name in NOT_CALLED) { expect(uses, `${name} is called now: take it out of NOT_CALLED`).toEqual([]); continue; }
      expect(uses.length, `${name} is generated and nothing calls it`).toBeGreaterThan(0);
      for (const [file, argument] of uses) expect(argument, `${file}: ${name}(${argument}…`).toMatch(/^encodeURIComponent\(/);
    }
  });

  it("a picture's address is the generated one, with the person's id encoded", async () => {
    const { avatarUrl } = await import("./ui/avatar");
    expect(avatarUrl("a/b?c", "e t")).toBe("/v1/users/a%2Fb%3Fc/avatar?v=e%20t");
    expect(avatarUrl("bob", null)).toBeNull();
  });

  it("an operation that is generated has no hand-written call left", () => {
    // every address the generated code calls, as it writes it: `/v1/cases/${caseId}/members`
    const addresses = [...new Set([...generated.matchAll(/return `(\/[^`?]*)`/g)].map((m) => m[1]))];
    expect(addresses).toEqual(expect.arrayContaining(["/v1/clock", "/health", "/v1/cases/${caseId}/members"]));
    for (const [file, text] of written) {
      for (const address of addresses) expect(names(text, address), `${file} still names ${address}`).toBe(false);
    }
  });

  it("which finds an address whatever its parts are called, and not a longer address that starts the same", () => {
    expect(names("fetch(`/v1/cases/${encodeURIComponent(id)}/members`)", "/v1/cases/${caseId}/members")).toBe(true);
    expect(names("fetch(`/v1/cases${closed ? \"?closed=true\" : \"\"}`)", "/v1/cases")).toBe(true);
    expect(names("fetch(\"/v1/cases\", { method: \"POST\" })", "/v1/cases")).toBe(true);
    expect(names("fetch(`/v1/cases/${encodeURIComponent(id)}?x=1`)", "/v1/cases/${caseId}")).toBe(true);
    expect(names("fetch('/v1/cases/' + encodeURIComponent(id) + '/members')", "/v1/cases/${caseId}/members")).toBe(true);
    expect(names("fetch(\"/v1/cases/\" + id)", "/v1/cases/${caseId}")).toBe(true);
    // a case's documents and playbooks are other operations, not generated yet
    expect(names("fetch(`/v1/cases/${encodeURIComponent(id)}/documents`)", "/v1/cases/${caseId}")).toBe(false);
    expect(names("fetch(`/v1/cases/${encodeURIComponent(id)}/documents`)", "/v1/cases")).toBe(false);
    expect(names("fetch(\"/v1/case-types-of-old\")", "/v1/case-types")).toBe(false);
  });
});
