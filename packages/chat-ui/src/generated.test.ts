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
};
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
    // every address the generated code calls, with a part of it as a pattern: `/v1/admin/clock/${rid}`
    const addresses = [...generated.matchAll(/return `(\/[^`?]*)`/g)].map((m) => m[1].replace(/\/\$\{\w+\}.*$/, ""));
    expect(addresses).toEqual(expect.arrayContaining(["/v1/clock", "/health"]));
    for (const [file, text] of written) {
      for (const address of new Set(addresses)) {
        expect(text.includes(`"${address}`) || text.includes(`\`${address}`), `${file} still names ${address}`).toBe(false);
      }
    }
  });
});
