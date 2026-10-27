/**
 * Stand-in answers for the setup API (api.ts), for `npm run dev` and the preview build (`vite build
 * --mode demo`) only: a production build never includes this file. It behaves like the appliance
 * will (#37 part 5) closely enough to walk through every screen, with the design's example values.
 * Nothing it says is checked: any .yaml file "is" a valid manifest here.
 *
 * Variants for trying things: add #check-fails to the address for a failed outgoing-traffic check,
 * #provisioning-fails for provisioning that stops at the sign-in step, #no-disk for no USB disk,
 * #restore-wrong-key for a recovery key that doesn't open the backup, #no-backup for a target without one.
 */
import type { BackupsAnswer, Manifest, Progress, RestoreProgress, RestoreStepId, SavedAnswers, SetupState, StepId } from "./api";
import { Refused } from "./api";

const variant = (v: string) => typeof location !== "undefined" && location.hash.includes(v);
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

const answers: SavedAnswers = {};
let progress: Progress | null = null;
let started = 0;
let failOnce = variant("provisioning-fails");

const STEPS: StepId[] = ["database", "signin", "models", "web", "outgoing"];
const RESTORE_STEPS: RestoreStepId[] = ["database", "restore", "models", "network", "services"];

let restore: RestoreProgress | null = null;
let restoreAt = 0;
const BACKUP = { file: "suveryn-backup_notary-brussels-01_20261023T023000Z.tar.zst.age", created: "2026-10-23T02:30:00Z",
                 appliance: "notary-brussels-01" };
const CHOICES = ["23", "22", "21", "16"].map((day, i) => ({
  file: `suveryn-backup_notary-brussels-01_202610${day}T023000Z.tar.zst.age`, created: `2026-10-${day}T02:30:00Z`,
  appliance: "notary-brussels-01", size: 1_240_000_000 - i * 3_000_000 }));

/** The check takes two seconds; the restore advances one step every 1.5 seconds. */
function currentRestore(): RestoreProgress | null {
  const r = restore;
  if (!r) return null;
  if (r.state === "checking" && Date.now() - restoreAt > 2000) {
    restore = variant("restore-wrong-key") ? { state: "failed", error: "wrong_key" }
      : variant("no-backup") ? { state: "failed", error: "no_backup" } : { state: "checked", backup: BACKUP, choices: CHOICES };
  } else if (r.state === "restoring") {
    const done = Math.floor((Date.now() - restoreAt) / 1500);
    r.steps = RESTORE_STEPS.map((id, i) => ({ id, state: i < done ? "done" : i === done ? "running" : "waiting" }));
    if (done >= RESTORE_STEPS.length) r.state = "done";
  }
  return structuredClone(restore);
}

function state(): SetupState {
  return {
    name: "notary-brussels-01", address: "192.168.1.50/24", dhcp: true, gateway: "192.168.1.1", dns: "192.168.1.1",
    language: null,
    appliance: { id: "7f3c9a2e-41b8-4d0e-9a6c-2e5d18b07f41",
                 fingerprint: "42a9e1f07c3d5b6a8e2f1c0d9b7a6e5f4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a" },
    models: ["Qwen3.8-27B", "Mistral Small 3.2"],
    usb_disks: variant("no-disk") ? [] : [{ id: "usb-SanDisk_Extreme_4C53000", name: "SanDisk Extreme", size_bytes: 1_000_204_886_016, bus: "USB 3" }],
    answers: structuredClone(answers),
    provisioning: progress && structuredClone(current()),
    restore: currentRestore(),
  };
}

/** Provisioning advances one step every 1.5 seconds. */
function current(): Progress {
  const p = progress!;
  if (p.state !== "running") return p;
  const done = Math.floor((Date.now() - started) / 1500);
  const failAt = failOnce ? 1 : -1;
  p.steps = STEPS.map((id, i) => ({
    id, state: i === failAt && done >= i ? "failed" : i < done ? "done" : i === done ? "running" : "waiting",
    ...(i === failAt && done >= i ? { error: "keycloak_unreachable" } : {}),
  }));
  if (failAt >= 0 && done >= failAt) { p.state = "failed"; failOnce = false; }
  else if (done >= STEPS.length) {
    p.state = "done";
    const mode = answers.network;
    p.outgoing = mode?.mode === "air-gapped" ? "blocked" : mode?.outgoing === "all" ? "not_checked"
      : variant("check-fails") ? "not_limited" : "limited";
  }
  return p;
}

const manifest = (): Manifest => ({
  edition: "Sūveryn Enterprise", appliance_id: "7f3c9a2e-41b8-4d0e-9a6c-2e5d18b07f41", users: 15,
  valid_until: "2027-09-30", next_check_in: "2026-12-31", connectors: 3, playbooks: 4,
});

type Body = Record<string, unknown>;

export async function answer(method: string, path: string, body?: unknown): Promise<unknown> {
  await wait(250);
  const b = (body ?? {}) as Body;
  switch (`${method} ${path}`) {
    case "GET state": return state();
    case "PUT answers/network": answers.network = b as never; return;
    case "PUT answers/administrator": answers.administrator = { name: String(b.name), email: String(b.email) }; return;
    case "PUT answers/certificate": {
      if (b.kind === "self-signed") return (answers.certificate = { kind: "self-signed", names: ["notary-brussels-01.local", "192.168.1.50"] });
      const errors: Record<string, string> = {};
      if (!String(b.certificate).includes("BEGIN CERTIFICATE")) errors.certificate = "not_a_certificate";
      if (!/BEGIN (RSA |EC )?PRIVATE KEY/.test(String(b.key))) errors.key = "not_a_key";
      if (b.chain && !String(b.chain).includes("BEGIN CERTIFICATE")) errors.chain = "not_a_certificate";
      if (Object.keys(errors).length) throw new Refused(errors);
      return (answers.certificate = { kind: "own", names: ["notary-brussels-01.local"], issuer: "Office CA", not_after: "2027-10-01" });
    }
    case "POST manifest": {
      const f = body as File;
      if (!/\.ya?ml$/i.test(f.name ?? "")) throw new Refused({ _: "manifest_format" });
      return (answers.support = manifest());
    }
    case "PUT answers/support": answers.support = null; return;
    case "POST backups/test": {
      const address = String(b.address);
      const ok = b.protocol === "nfs" ? /^[\w.-]+:\/\S+$/.test(address) : /^(\\\\|\/\/)[\w.-]+[\\/]\S+$/.test(address);
      if (!ok) return { ok: false, error: "address" };
      if (/fail/i.test(address)) return { ok: false, error: "unreachable" };
      return { ok: true };
    }
    case "PUT answers/backups": { const { password: _p, ...rest } = b; void _p; answers.backups = rest as BackupsAnswer; return; }
    case "POST provision":
      started = Date.now();
      progress = { state: "running", steps: [], outgoing: null };
      return structuredClone(current());
    case "PUT answers/restore": {
      if (!/AGE-SECRET-KEY-1[0-9A-Z]{58}/.test(String(b.key))) throw new Refused({ key: "key_invalid" });
      if (b.target === "share" && !/^(\\\\|\/\/)[\w.-]+[\\/]\S+$|^[\w.-]+:\/\S+$/.test(String(b.address))) {
        throw new Refused({ address: "address" });
      }
      restoreAt = Date.now();
      restore = { state: "checking" };
      return currentRestore();
    }
    case "POST restore/start":
      if (restore?.state !== "checked") throw new Refused({ _: "not_checked" });
      if (b?.file !== undefined && !CHOICES.some((c) => c.file === b.file)) throw new Refused({ file: "invalid" });
      restoreAt = Date.now();
      restore = { ...restore, backup: CHOICES.find((c) => c.file === b?.file) ?? BACKUP, state: "restoring",
                  address: `https://${BACKUP.appliance}.local`, steps: [] };
      return currentRestore();
    case "GET restore": return currentRestore();
    // A copy each time, like JSON from the appliance (React keeps an unchanged object as it was).
    case "GET provision": return progress && structuredClone(current());
  }
  throw new Error(`demo: no answer for ${method} ${path}`);
}
