/**
 * The web setup's logic outside the screens: the backup recovery key (age format), the registration
 * link and fingerprint, disk sizes, the appliance's refusals as messages, and that the demo answers
 * stay out of production builds. The screens themselves are checked in a browser
 * (docs/spikes/react-aria/check.py).
 */
import { createPrivateKey, createPublicKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Refused } from "./api";
import { bech32, makeRecoveryKey, recoveryKeyFile } from "./recoveryKey";
import { diskSize } from "./steps/Backups";
import { errorsFrom } from "./steps/common";
import { groupedFingerprint, registrationUrl } from "./steps/Support";
import { TEXT } from "./text";

const CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
/** The 32 bytes in a bech32 string (without checking its checksum). */
function bytesOf(s: string): Uint8Array {
  const data = s.toLowerCase().slice(s.lastIndexOf("1") + 1, -6);
  const out: number[] = [];
  let acc = 0;
  let bits = 0;
  for (const c of data) {
    acc = (acc << 5) | CHARSET.indexOf(c);
    bits += 5;
    if (bits >= 8) { bits -= 8; out.push((acc >>> bits) & 255); }
  }
  return Uint8Array.from(out);
}
/** The X25519 public key for a private one, by Node's own crypto. */
function publicOf(priv: Uint8Array): Uint8Array {
  const der = Buffer.concat([Buffer.from("302e020100300506032b656e04220420", "hex"), Buffer.from(priv)]);
  const jwk = createPublicKey(createPrivateKey({ key: der, format: "der", type: "pkcs8" })).export({ format: "jwk" });
  return Uint8Array.from(Buffer.from(jwk.x!, "base64url"));
}

describe("the backup recovery key (age X25519)", () => {
  // A throwaway pair made by age-keygen (age 1.1), as a fixed reference. Not used anywhere.
  const IDENTITY = "AGE-SECRET-KEY-1QUWSUERY2XGZL7VXG4ESMNXM47SLUYM0NVLSV276T5XJJDWL7TUQ6RN0YU";
  const RECIPIENT = "age166srcke2l538za388de4cly32dhk96rg8yp6ckng0962fderf3yq64whup";

  it("encodes keys exactly as age does", () => {
    const priv = bytesOf(IDENTITY);
    expect(bech32("age-secret-key-", priv).toUpperCase()).toBe(IDENTITY);
    expect(bech32("age", publicOf(priv))).toBe(RECIPIENT);
  });
  it("makes a pair whose public half belongs to its private half", async () => {
    const k = await makeRecoveryKey();
    expect(k.identity).toMatch(/^AGE-SECRET-KEY-1[0-9A-Z]{58}$/);
    expect(k.recipient).toMatch(/^age1[0-9a-z]{58}$/);
    expect(bech32("age", publicOf(bytesOf(k.identity)))).toBe(k.recipient);
  });
  it("writes an age identity file: comments, then the private key", async () => {
    const k = await makeRecoveryKey();
    const f = recoveryKeyFile(k, { name: "notary-brussels-01", id: "7f3c9a2e" }, new Date("2026-10-15T10:00:00Z"),
                              { title: TEXT.en.keyFileTitle, keep: TEXT.en.keyFileKeep });
    const lines = f.trim().split("\n");
    expect(lines.slice(0, -1).every((l) => l.startsWith("# "))).toBe(true);
    expect(lines.at(-1)).toBe(k.identity);
    expect(f).toContain(`# public key: ${k.recipient}`);
    expect(f).toContain("notary-brussels-01 (7f3c9a2e), 2026-10-15");
  });
});

describe("registration (support agreement)", () => {
  const fp = "42a9e1f07c3d5b6a8e2f1c0d9b7a6e5f4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a";
  it("links to the portal with the ID and the fingerprint's first 16 characters, as the console does", () => {
    expect(registrationUrl("7f3c9a2e-41b8-4d0e-9a6c-2e5d18b07f41", fp))
      .toBe("https://portal.suveryn.com/r/7f3c9a2e-41b8-4d0e-9a6c-2e5d18b07f41?k=42a9e1f07c3d5b6a");
  });
  it("shows the fingerprint in groups of four", () => {
    expect(groupedFingerprint(fp)).toBe(`SHA256:${fp.match(/.{4}/g)!.join(" ")}`);
  });
});

describe("the rest", () => {
  it("gives disk sizes in decimal units, in the interface's language", () => {
    expect(diskSize(1_000_204_886_016, "en-GB")).toBe("1 TB");
    expect(diskSize(500_107_862_016, "nl-BE")).toBe("500 GB");
    expect(diskSize(2_500_000_000_000, "fr-BE")).toBe("2,5 TB");
  });
  it("turns the appliance's refusal codes into messages, and anything else into one message", () => {
    const t = TEXT.nl;
    expect(errorsFrom(new Refused({ key: "key_mismatch", _: "nonsense" }), t)).toEqual({ key: t.errors.key_mismatch, _: t.errUnexpected });
    expect(errorsFrom(new Error("HTTP 500"), t)).toEqual({ _: t.errUnexpected });
  });
  it("has a message for every code in every language", () => {
    for (const code of Object.keys(TEXT.en.errors)) {
      expect(TEXT.nl.errors[code], code).toBeTruthy();
      expect(TEXT.fr.errors[code], code).toBeTruthy();
    }
  });
  it("loads the demo answers only in development and the preview build", () => {
    const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
    const uses = api.split("\n").filter((l) => l.includes('import("./demo")'));
    expect(uses).toHaveLength(1);
    expect(uses[0]).toMatch(/if \(import\.meta\.env\.DEV \|\| import\.meta\.env\.MODE === "demo"\)/);
  });
});
