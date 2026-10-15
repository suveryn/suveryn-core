/**
 * The backup recovery key (setup screen 5, suveryn-tracker#33, #37), made in the browser: an X25519
 * key pair in the format of age (https://age-encryption.org/v1), a small, widely reviewed file
 * encryption tool. The appliance gets only the public half (the "recipient", age1…), so it can
 * encrypt backups but never read them; the private half (AGE-SECRET-KEY-1…) is downloaded as an age
 * identity file and never leaves this browser any other way. Restoring a backup needs that file.
 *
 * Made with the browser's own Web Crypto (X25519); nothing is sent while making it.
 */

const CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

function polymod(values: number[]): number {
  const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  let chk = 1;
  for (const v of values) {
    const top = chk >>> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ v;
    for (let i = 0; i < 5; i++) if ((top >>> i) & 1) chk ^= GEN[i];
  }
  return chk >>> 0;
}

function toWords(bytes: Uint8Array): number[] {
  const words: number[] = [];
  let acc = 0;
  let bits = 0;
  for (const b of bytes) {
    acc = (acc << 8) | b;
    bits += 8;
    while (bits >= 5) { bits -= 5; words.push((acc >>> bits) & 31); }
  }
  if (bits > 0) words.push((acc << (5 - bits)) & 31);
  return words;
}

/** Bech32 (BIP 173), as age uses it, without the 90-character limit. */
export function bech32(hrp: string, bytes: Uint8Array): string {
  const data = toWords(bytes);
  const expand = [...hrp].map((c) => c.charCodeAt(0) >> 5).concat([0], [...hrp].map((c) => c.charCodeAt(0) & 31));
  const mod = polymod([...expand, ...data, 0, 0, 0, 0, 0, 0]) ^ 1;
  const checksum = [0, 1, 2, 3, 4, 5].map((i) => (mod >>> (5 * (5 - i))) & 31);
  return `${hrp}1${[...data, ...checksum].map((d) => CHARSET[d]).join("")}`;
}

const fromBase64Url = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

export type RecoveryKey = { recipient: string; identity: string };

/** Whether this browser can make the key (X25519 in Web Crypto: current Safari, Chrome, Firefox, Edge). */
export async function canMakeRecoveryKey(): Promise<boolean> {
  try {
    await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
    return true;
  } catch {
    return false;
  }
}

/** A new key pair: the public recipient (age1…) and the private identity (AGE-SECRET-KEY-1…). */
export async function makeRecoveryKey(): Promise<RecoveryKey> {
  const pair = (await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"])) as CryptoKeyPair;
  const pub = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  const d = (await crypto.subtle.exportKey("jwk", pair.privateKey)).d!;
  return { recipient: bech32("age", pub), identity: bech32("age-secret-key-", fromBase64Url(d)).toUpperCase() };
}

/** The file to keep offline: an age identity file, with what it is for in comment lines. */
export function recoveryKeyFile(key: RecoveryKey, appliance: { name: string; id: string | null }, created: Date,
                                lines: { title: string; keep: string }): string {
  return [
    `# ${lines.title}`,
    `# ${appliance.name}${appliance.id ? ` (${appliance.id})` : ""}, ${created.toISOString().slice(0, 10)}`,
    `# ${lines.keep}`,
    `# public key: ${key.recipient}`,
    key.identity,
    "",
  ].join("\n");
}
