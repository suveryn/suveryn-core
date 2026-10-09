import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import lock from "./brand-lock.json";

// The brand files and tokens.css are copies from suveryn-brand (scripts/brand-sync.mjs). Editing one
// by hand makes it drift from the brand; change suveryn-brand instead and run `npm run brand:sync`.
describe("brand files", () => {
  for (const [path, hash] of Object.entries(lock.files)) {
    it(`${path} matches suveryn-brand@${lock.commit.slice(0, 7)}`, () => {
      expect(createHash("sha256").update(readFileSync(path)).digest("hex")).toBe(hash);
    });
  }
});
