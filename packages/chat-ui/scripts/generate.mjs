// The chat UI's code for the gateway, generated from the gateway's description (packages/api-gateway/openapi.json)
// by Orval (orval.config.ts; README.md, "The gateway's code (generated)"; suveryn-tracker#159, #236).
//
//   npm run generate              write src/generated
//   npm run generate -- --check   write nothing; fail when src/generated isn't what the description gives
//
// `npm test` runs the check first.
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = resolve(fileURLToPath(import.meta.url), "../..");
const generated = join(here, "src/generated");
const FILE = "gateway.ts";
const check = process.argv.includes("--check");

// checked in a folder beside src/generated, removed after: the generated file reaches the one hand-written fetch
// (src/lib/gateway.ts) by a path from where it is written
const out = check ? mkdtempSync(join(here, "src/generated-check-")) : generated;
try {
  if (!check) rmSync(generated, { recursive: true, force: true }); // a file the generator no longer writes goes
  execFileSync(join(here, "node_modules/.bin/orval"), [], { cwd: here, stdio: ["ignore", "ignore", "inherit"],
    env: { ...process.env, SUVERYN_GENERATED: join(out, FILE) } });
  const now = readFileSync(join(out, FILE), "utf8");
  if (check) {
    if (!existsSync(join(generated, FILE)) || readFileSync(join(generated, FILE), "utf8") !== now) {
      console.error("src/generated isn't what the gateway's description gives: run `npm run generate` and commit it with the change");
      process.exitCode = 1;
    }
  } else {
    console.log(`wrote src/generated/${FILE}`);
  }
} finally {
  if (check) rmSync(out, { recursive: true, force: true });
}
