/**
 * What the web setup asks the appliance (suveryn-tracker#37). Same origin, served by the appliance only
 * until setup finishes, with no sign-in (setup is what creates the first account). The paths are
 * relative: the appliance serves setup at / (or /setup.html), so `setup/v1/…` is `/setup/v1/…` either way.
 *
 * Each step's answers are saved on the appliance when Continue is pressed, so a reload resumes where
 * it was and secrets (the administrator's password, the share's password, a private key) pass through
 * the page once and aren't kept in it. The appliance checks everything again; the codes it answers
 * with are shown in the interface's language (`errors` in i18n/<lang>.ts).
 *
 *   GET  setup/v1/state                    → SetupState
 *   PUT  setup/v1/answers/network          { mode, outgoing }
 *   PUT  setup/v1/answers/administrator    { name, email, password }
 *   PUT  setup/v1/answers/certificate      { kind: "self-signed" } | { kind: "own", certificate, key, chain? } (PEM text)
 *                                          → CertificateAnswer
 *   POST setup/v1/manifest                 the manifest file's bytes → Manifest (and saves it)
 *   PUT  setup/v1/answers/support          { skipped: true }
 *   POST setup/v1/backups/test             { protocol, address, user?, password? } → { ok: true } | { ok: false, error }
 *   PUT  setup/v1/answers/backups          BackupsAnswer, plus password for a share
 *   POST setup/v1/provision                → Progress (starts it; again after a failure retries)
 *   GET  setup/v1/provision                → Progress
 *   PUT  setup/v1/answers/restore          RestoreAnswer → RestoreProgress (checking: the appliance finds the
 *                                          backups there the key opens, its appliance's, and checks the newest, #56)
 *   POST setup/v1/restore/start            { file } → RestoreProgress (restores the chosen one of those)
 *   GET  setup/v1/restore                  → RestoreProgress | null
 *
 * Errors: 422 with { errors: { field: code } } or { error: code }. The appliance answers these with
 * suveryn-appliance's setup/suveryn-setup (#37 part 5); `npm run dev` and the preview build
 * (`--mode demo`) answer from demo.ts instead.
 */

export type NetworkMode = "connected" | "air-gapped";
export type Outgoing = "approved" | "all";
export type NetworkAnswer = { mode: NetworkMode; outgoing: Outgoing };
export type AdministratorAnswer = { name: string; email: string };
export type CertificateAnswer =
  | { kind: "self-signed"; names: string[] }
  | { kind: "own"; names: string[]; issuer: string; not_after: string };
/** A support agreement manifest, checked on the appliance (signed by Sūveryn Labs for this appliance). */
export type Manifest = {
  edition: string;            // e.g. "Sūveryn Enterprise"
  appliance_id: string;
  users: number;
  valid_until: string;        // ISO date
  next_check_in: string;      // ISO date
  connectors: number;
  playbooks: number;
};
export type Retention = 14 | 30 | 90 | 365;
export type BackupsAnswer =
  | { target: "usb"; disk: string; retention_days: Retention; recipient: string }
  | { target: "share"; protocol: "smb" | "nfs"; address: string; user: string | null; retention_days: Retention; recipient: string }
  | { target: "later" };
export type UsbDisk = { id: string; name: string; size_bytes: number; bus: string };

/** Where a replacement appliance finds the office's backups, and the recovery key (the text of the file
 *  setup made, or just its AGE-SECRET-KEY-1… line). The key and a share's password are kept on the
 *  appliance only until the restore, then deleted. */
export type RestoreAnswer =
  | { target: "usb"; disk: string; key: string }
  | { target: "share"; protocol: "smb" | "nfs"; address: string; user?: string; password?: string; key: string };
export type RestoreStepId = "database" | "restore" | "models" | "network" | "services";
export type RestoreProgress = {
  state: "checking" | "checked" | "restoring" | "done" | "failed";
  /** The backup the check found: its file, when it was made, and the name of the appliance that made it. */
  backup?: { file: string; created: string; appliance: string };
  /** Every backup the key opens, newest first: the office may choose an older one. Another appliance's
   * backups are never among them, even when they are newer (each appliance has its own key). */
  choices?: { file: string; created: string; appliance: string; size: number }[];
  /** Where the restored appliance answers: it takes the old appliance's name. */
  address?: string;
  steps?: { id: RestoreStepId; state: "waiting" | "running" | "done" | "failed" }[];
  error?: string;
};

export type SavedAnswers = {
  network?: NetworkAnswer;
  administrator?: AdministratorAnswer;    // the password stays on the appliance
  certificate?: CertificateAnswer;
  support?: Manifest | null;              // null: skipped
  backups?: BackupsAnswer;
};

export type SetupState = {
  name: string;               // e.g. notary-brussels-01 (reached as <name>.local)
  address: string;            // with prefix, e.g. 192.168.1.50/24
  dhcp: boolean;
  gateway: string;
  dns: string;
  language: string | null;    // chosen at installation: en, nl or fr
  appliance: { id: string; fingerprint: string } | null;  // the identity (#35): UUID and SHA-256 of its public key, hex
  models: string[];           // installed language models, by name
  usb_disks: UsbDisk[];       // disks plugged into the appliance that could hold backups
  answers: SavedAnswers;
  provisioning: Progress | null;
  restore: RestoreProgress | null;
};

export type StepId = "database" | "signin" | "models" | "web" | "outgoing";
export type Progress = {
  state: "running" | "done" | "failed";
  steps: { id: StepId; state: "waiting" | "running" | "done" | "failed"; error?: string }[];
  /** The last check: what the appliance could reach. not_checked: "allow all outgoing traffic". */
  outgoing: "limited" | "blocked" | "not_limited" | "not_checked" | null;
};

/** An answer the appliance refused, by field (or `_` for the whole step), as codes. */
export class Refused extends Error {
  constructor(readonly codes: Record<string, string>) { super(Object.values(codes).join(", ")); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Development and the preview build only; a production build leaves demo.ts out entirely.
  if (import.meta.env.DEV || import.meta.env.MODE === "demo") return (await import("./demo")).answer(method, path, body) as Promise<T>;
  const r = await fetch(`setup/v1/${path}`, {
    method,
    headers: body === undefined ? { Accept: "application/json" }
      : body instanceof Blob ? { "Content-Type": "application/octet-stream" } : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body),
  });
  if (r.status === 422) {
    const e = await r.json().catch(() => ({}));
    throw new Refused(e.errors ?? { _: e.error ?? "refused" });
  }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const getState = () => call<SetupState>("GET", "state");
export const saveNetwork = (a: NetworkAnswer) => call<void>("PUT", "answers/network", a);
export const saveAdministrator = (a: AdministratorAnswer & { password: string }) => call<void>("PUT", "answers/administrator", a);
export const saveCertificate = (a: { kind: "self-signed" } | { kind: "own"; certificate: string; key: string; chain?: string }) =>
  call<CertificateAnswer>("PUT", "answers/certificate", a);
export const checkManifest = (file: Blob) => call<Manifest>("POST", "manifest", file);
export const skipManifest = () => call<void>("PUT", "answers/support", { skipped: true });
export const testShare = (s: { protocol: "smb" | "nfs"; address: string; user?: string; password?: string }) =>
  call<{ ok: true } | { ok: false; error: string }>("POST", "backups/test", s);
export const saveBackups = (a: BackupsAnswer & { password?: string }) => call<void>("PUT", "answers/backups", a);
export const startProvisioning = () => call<Progress>("POST", "provision");
export const getProgress = () => call<Progress>("GET", "provision");
export const saveRestore = (a: RestoreAnswer) => call<RestoreProgress>("PUT", "answers/restore", a);
export const startRestore = (file?: string) => call<RestoreProgress>("POST", "restore/start", file ? { file } : undefined);
export const getRestore = () => call<RestoreProgress | null>("GET", "restore");
