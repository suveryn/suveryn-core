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

describe("calling generated code", () => {
  it("an id put into an address is encoded by the caller: Orval puts it in as it is given", () => {
    // the generated calls whose address takes a part: `export const getClockRequest = async (rid: string, …`
    const withPart = [...generated.matchAll(/export const get(\w+)Url = \((\w+): string/g)]
      .map((m) => m[1][0].toLowerCase() + m[1].slice(1));
    expect(withPart).toContain("getClockRequest");
    for (const name of withPart) {
      const uses = written.flatMap(([file, text]) => [...text.matchAll(new RegExp(`\\b${name}\\(([^)]*)`, "g"))].map((m) => [file, m[1]] as const));
      expect(uses.length, `${name} is generated and nothing calls it`).toBeGreaterThan(0);
      for (const [file, argument] of uses) expect(argument, `${file}: ${name}(${argument}…`).toMatch(/^encodeURIComponent\(/);
    }
  });

  it("an operation that is generated has no hand-written call left", () => {
    // every address the generated code calls, with a part of it as a pattern: `/v1/admin/clock/${rid}`
    const addresses = [...generated.matchAll(/return `(\/v1\/[^`?]*)`/g)].map((m) => m[1].replace(/\/\$\{\w+\}.*$/, ""));
    expect(addresses).toContain("/v1/clock");
    for (const [file, text] of written) {
      for (const address of new Set(addresses)) {
        expect(text.includes(`"${address}`) || text.includes(`\`${address}`), `${file} still names ${address}`).toBe(false);
      }
    }
  });
});
