/**
 * The gateway API, as used by the UI. All calls are relative (same origin); in development Vite
 * proxies them to the gateway. No other host is ever contacted.
 */
import { clearDraft } from "./lib/draft";
import { createSSEParser } from "./lib/sse";
import { RateLimited } from "./lib/turns";
import { lang, t } from "./i18n";
import { messageText, problemOf, type Message } from "./lib/messages";
import type { Turn } from "./types";
import type { SavedAnswer } from "./lib/saved";
import * as gateway from "./generated/gateway";
import { reach, Unreachable, type Answer } from "./lib/gateway";

/** A shape of the gateway's answer as a saved turn keeps it: a turn saved before the gateway said `Lacking` doesn't
 *  have it. The screens read a turn's passages, calculations and marks through these. */
type Kept<Shape, Lacking extends keyof Shape> = Omit<Shape, Lacking> & Partial<Pick<Shape, Lacking>>;
type SourceRef = Kept<gateway.SourceRef, "decimals">;
/** A passage an answer was written from. ``removed``: its document was deleted, so the passage was taken out of the
 *  saved turn (suveryn-tracker#12): the conversation's own mark, not the gateway's answer's. ``context``: the text
 *  around it on its page (board G11): the passage is ``text.slice(start, end)``. */
export type Citation = Omit<Kept<gateway.Citation, "context">, "source"> & { source: SourceRef | null; removed?: boolean };
/** A fact in a cited claim that the cited passage doesn't contain (suveryn-tracker#11). ``marker`` is the
 *  0-based place of the [n] among the answer's valid markers; ``found_in``: other passages that do contain it. */
export type CitationIssue = gateway.CitationIssue;
/** A calculation the server computed exactly; the model only chose the figures. ``result`` null: it couldn't be
 *  computed (``code`` says why, a code of the registry; ``error`` in English, for developers);
 *  ``figures_not_in_sources``: figures to check, which don't appear in the passages given; ``read_as``: figures that
 *  read either way ("28.848"), read as the documents that write them write decimals. */
export type Calculation = Kept<gateway.Calculation, "code" | "read_as" | "read_with">;
/** What the source card marks for one marker, from the server (suveryn-tracker#25): the sentences of passage ``n``
 *  the claim rests on, and its facts; [start, end) offsets into the passage's text. ``how`` "meaning": found by the
 *  embedding model, in other words or another language (step 3). */
export type SupportSpan = Kept<gateway.SupportSpan, "how">;
/** A whole answer. ``unverified_figures``: figures in no passage and no calculation's result, to flag for checking;
 *  ``citation_issues``: facts the cited passage doesn't contain, to flag the marker; ``instruction_like_sources``:
 *  passages whose text addresses an AI, to tell the reader (suveryn-tracker#21); ``reasoning``, ``thought_seconds``:
 *  *Thorough*, what the model thought before answering (never in ``answer``) and for how long; ``thinking_cut``: it
 *  thought past its allowance and was answered again without thinking; ``narrowed_to``: the question named one
 *  document, and only that one was read. */
export type ChatResponse = gateway.ChatResponse;

/** An upload's state. */
export type JobStatus = gateway.Upload["status"];
/** How far reading has got (suveryn_rag.reading.Progress): text recognition page by page, the layout, storing. */
export type JobProgress = gateway.Progress;
/** What a reading noticed: a warning of the registry's document area with its page (`params.page`; none for a file
 *  without pages), and its detail, in English, for developers. */
export type Warning = gateway.ReadingWarning;
/** An upload on its way to being a document. `failure`: why it failed, a code of the registry's document area with
 *  its numbers, worded here; `noticed`: the file carries sūveryn's own export mark, so it is no source until someone
 *  says so. */
export type Job = gateway.Upload;

/** A .zip upload: a job per document, and the files left out, each with why as a code of the registry. */
export type ArchiveUpload = gateway.ArchiveUpload;
export const isArchiveUpload = (r: Job | ArchiveUpload): r is ArchiveUpload => "jobs" in r;
/** sūveryn's export mark found in an upload (docs/design/chat-ui.md §6): the line as it stands in the file. */
export type Noticed = gateway.Noticed;
/** A stored document. `origin`: only uploaded documents are sources for answers (suveryn-tracker#10); `source`: the
 *  model may read and cite it (cases.md decision 7; the server decides); `provenance`: more about where it came from
 *  (docs/design/chat-ui.md §6), only what is known of it: a playbook's result, or an upload that looked like sūveryn's
 *  own output and who chose to use it anyway. */
export type StoredDocument = gateway.StoredDocument;
/** A document with where it is (`case_id` null: the personal space). */
export type PlacedDocument = gateway.PlacedDocument;
/** What the appliance says of its own health: states only (it is public). The same body whether the model server is ready or not. */
export type Health = gateway.HealthResponse;
// admin: may open the administration page; office_wide: a new case is open to the whole office by
// default; cases_keep: how long a closed case is kept before it is deleted ("manual": until deleted by hand)
export type KeepPeriod = gateway.Me["cases_keep"];
// avatar: the ETag of the user's picture (null: initials are shown); see Avatar in the UI kit
// account_url: where the person changes their password (Keycloak's account console); null with sign-in off
// office_name: the office's name (Administration › Settings), after the person's name; null: not set
// admin_console_url: administrators, the sign-in service's own console; null when there is none
export type Me = gateway.Me;
/** A pipeline step the server reports before the answer's first word (SSE event `status`). */
export type StreamStatus = gateway.StreamStatus;
/** The events of a streamed answer, by name, each with its data (the gateway's description names the same ones:
 *  src/api.answers.test.ts holds this list to it). */
type AnswerEvents = { status: gateway.StreamStatus; sources: gateway.StreamSources; thinking: gateway.StreamThinking; delta: gateway.StreamDelta;
                      done: gateway.ChatResponse; error: gateway.StreamError };
const EVERY_EVENT: Record<keyof AnswerEvents, true> = { status: true, sources: true, thinking: true, delta: true, done: true, error: true };
export const ANSWER_EVENTS = Object.keys(EVERY_EVENT);
/** An answer in a saved conversation says the numbers the server gave its question and itself too (`stored`, #251). */
type ConversationEvents = AnswerEvents & { stored: gateway.StoredTurns };
export const CONVERSATION_EVENTS = ["stored", ...ANSWER_EVENTS];
/** An installed model; only one is in GPU memory at a time. `thinks`: the model can think before it answers, so
 *  *Thorough* is possible (docs/design/chat-ui.md §5). */
export type { ModelInfo } from "./generated/gateway";

/**
 * Sign-in. The gateway runs the OIDC login with Keycloak and keeps the tokens; the browser only
 * holds an HttpOnly session cookie that fetch and XHR send automatically (same origin). A 401 from
 * any API call means the session ended: the registered handler shows the sign-in screen.
 */
class SignedOut extends Error {
  constructor() { super(messageText({ code: "auth.signed_out" }, t())); }
}
let signedOutHandler: () => void = () => {};
export function onSignedOut(handler: () => void): void { signedOutHandler = handler; }

/** A refused request: its sentence for the person, and the status, for a page that acts on it. */
/** A streamed answer that failed: the words as of now, and the message itself (its code, kind and values), so a
 *  saved turn is worded again, in the reader's language of that day, when it is shown. */
export class StreamFailure extends Error {
  constructor(message: string, readonly failure: Message) { super(message); }
}

export class HttpError extends Error {
  /** `problem`: the gateway's code and its values (Problem Details), or the status's general code for an answer
   *  that isn't the gateway's own; for a screen that acts on them. */
  constructor(message: string, readonly status: number, readonly problem?: Message) { super(message); }
}

async function responseError(r: Response): Promise<Error> {
  if (r.status === 401) { signedOutHandler(); return new SignedOut(); }
  const body = await errorBody(r);
  return new HttpError(httpErrorText(r.status, body), r.status, problemOf(r.status, body));
}

/** The signed-in user, or null if signed out. Throws if sign-in itself is unavailable. */
export async function getMe(): Promise<Me | null> {
  const answer = await gateway.getMe();
  if (answer.status === 200 && answer.data) return answer.data;
  if (answer.status === 401) return null;
  throw new Error(httpErrorText(answer.status, answer.data));
}

/** Fired on window when what /auth/me says has changed (the office's name): the app reads it again. */
export const ME_CHANGED = "suveryn:me-changed";

/** Goes to the Keycloak login page (through the gateway); comes back to the chat. */
export function signIn(): void {
  window.location.assign(`/auth/login?return_to=/&lang=${lang()}`);
}

/** Ends the session in the gateway, then in Keycloak (its logout page sends the browser back). */
export async function signOut(): Promise<void> {
  clearDraft();  // a question typed but not sent doesn't outlive the session on this computer
  let url: string | null = null;
  try {
    const answer = await gateway.signOut();
    url = answer.status === 200 ? answer.data?.logout_url ?? null : null;
  } catch { /* the session is dropped anyway when it expires */ }
  window.location.assign(url ?? "/");
}

/**
 * What went wrong, in the interface's language: the answer's code (the gateway's Problem Details; lib/messages.ts),
 * else the general code of its status. The server's own English is never shown.
 */
export function httpErrorText(status: number, body: unknown = null): string {
  return messageText(problemOf(status, body), t());
}

/** An error answer's body: the gateway's Problem Details, or null when it isn't JSON (a proxy's page). */
async function errorBody(r: Response): Promise<unknown> {
  try { return await r.json(); } catch { return null; }
}

/** The appliance's state, or null when the gateway isn't reached or answers something else. While the model server
 *  isn't ready the status is 503 and the body the same. */
export async function getHealth(): Promise<Health | null> {
  try {
    const answer = await gateway.getHealth();
    return answer.status === 200 || answer.status === 503 ? answer.data ?? null : null;
  } catch {
    return null; // gateway not reachable
  }
}

/** `?case=<id>` on a request about a case; nothing for the personal space (suveryn-tracker#10). */
const inCase = (caseId: string | null | undefined) => (caseId ? { case: caseId } : undefined);

/** The file a document was read from, as uploaded (board G11): a PDF opens at ``page``. A plain link, so the
 *  browser opens it in a new tab with the session cookie; the gateway checks the scope as for its passages. The
 *  address is the generated one. */
export const originalUrl = (documentId: string, caseId?: string | null, page?: number | null) =>
  `${gateway.getGetDocumentOriginalUrl(encodeURIComponent(documentId), inCase(caseId))}${page ? `#page=${page}` : ""}`;

/**
 * Uploads a document (PDF, Word, Excel, Markdown or CSV: lib/formats.ts) and resolves with its job, or a
 * .zip of them and resolves with a job per document inside (ArchiveUpload). Uses XMLHttpRequest rather
 * than the generated call's fetch because only XHR reports upload progress; `onProgress` gets a fraction from 0 to 1.
 */
export function uploadDocument(file: File, onProgress?: (fraction: number) => void, caseId?: string | null,
                               signal?: AbortSignal): Promise<Job | ArchiveUpload> {
  return new Promise((resolve, reject) => {
    // what is sent, and where, are the generated code's: only the sending is this function's own
    const body: gateway.BodyCreateUpload = { file };
    const form = new FormData();
    for (const [name, part] of Object.entries(body)) form.append(name, part, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", gateway.getCreateUploadUrl(inCase(caseId)));
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Job | ArchiveUpload);
      else if (xhr.status === 401) { signedOutHandler(); reject(new SignedOut()); }
      else {
        const after = xhr.getResponseHeader("Retry-After");
        const text = httpErrorText(xhr.status, xhr.response);
        // The per-person rate limit, or a full reading queue: the chat waits its turn (lib/turns.ts). The queue
        // names no time; it empties as documents are read, so the chat looks again every 10 seconds.
        const queueFull = xhr.response?.code === "upload.too_many";
        const rateLimited = xhr.status === 429 && xhr.response?.code !== "run.too_many";
        reject(rateLimited ? new RateLimited(text, after && /^\d+$/.test(after) ? Number(after) : queueFull ? 10 : 30) : new Error(text));
      }
    };
    xhr.onerror = () => reject(new Error(t().uploadInterrupted));
    xhr.onabort = () => reject(new DOMException("cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

/** What a streamed answer says as it comes. */
export type AnswerHandlers = {
  onDelta: (text: string) => void;
  onStatus?: (status: StreamStatus) => void;
  onSources?: (citations: Citation[]) => void;  // a grounded answer's passages, before its first word
  onThinking?: (text: string) => void;          // *Thorough*: the reasoning as it comes
  /** In a saved conversation: the numbers the server gave the question, first, then the answer too, once stored. */
  onStored?: (stored: gateway.StoredTurns) => void;
};

/**
 * A question asked in a saved conversation (suveryn-tracker#251): the server stores it, reads the model what it stored
 * of the conversation on the way to it (the answer it follows, `after`), and stores the answer as it is written,
 * however it ends. `again`: Regenerate, the question (its `seq`) once more as it was asked. Calls `onDelta` with each
 * piece of text, then resolves with the whole answer; rejects if the stream ends in an `error` event or breaks off (any
 * partial text is then discarded: the gateway's contract).
 */
export async function askInConversation(conversationId: string, question: gateway.QuestionIn, handlers: AnswerHandlers,
                                        signal?: AbortSignal): Promise<ChatResponse> {
  const r = await reach(gateway.getAskInConversationUrl(encodeURIComponent(conversationId)), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(question), signal });
  return readAnswer(r, handlers);
}

async function readAnswer(r: Response, h: AnswerHandlers): Promise<ChatResponse> {
  if (!r.ok || !r.body) throw await responseError(r);
  let done: ChatResponse | null = null;
  let failure: Message | null = null;
  const said = <Name extends keyof ConversationEvents>(_: Name, data: string) => JSON.parse(data) as ConversationEvents[Name];
  const parser = createSSEParser(({ event, data }) => {
    if (event === "stored") h.onStored?.(said(event, data));
    else if (event === "status") h.onStatus?.(said(event, data));
    else if (event === "sources") h.onSources?.(said(event, data).citations);
    else if (event === "thinking") h.onThinking?.(said(event, data).text);
    else if (event === "delta") h.onDelta(said(event, data).text);
    else if (event === "done") done = said(event, data);
    else if (event === "error") {
      // What failed, as every message is said: a code with its kind and values (docs/design/messages.md), worded
      // here; a code this page doesn't know gets its area's or its kind's words, never the server's English.
      const { kind, code, params } = said(event, data);
      failure = { kind, code, params: params ?? {} };
    }
  });
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    let read: ReadableStreamReadResult<string>;
    try {
      read = await reader.read();
    } catch (e) {  // the connection broke while the answer came
      throw e instanceof TypeError ? new Unreachable(t().streamCutOff) : e;
    }
    if (read.done) break;
    parser.feed(read.value);
  }
  if (failure) throw new StreamFailure(messageText(failure, t()), failure);
  if (!done) throw new Error(t().streamCutOff);
  return done;
}

/** Pages where text may be missing (the warnings that put a document in needs_review). */
export function reviewPages(warnings: Warning[] | undefined): number[] {
  return pagesWith(warnings, ["document.page_coverage_low", "document.layout_failed"]);
}

/** The pages the warnings of these codes are about, each once, in order. */
export function pagesWith(warnings: Warning[] | undefined, codes: string[]): number[] {
  const pages = (warnings ?? []).filter((w) => codes.includes(w.code ?? "")).map((w) => w.params?.page).filter((p): p is number => typeof p === "number");
  return [...new Set(pages)].sort((a, b) => a - b);
}

/** A saved conversation in a list: no content, newest first. `owner`: who started it (a Keycloak id); `shared`: shared
 *  with the case's members (stage 4), read-only for them; `shielded`: in a strictly confidential case, so no title in
 *  the lists that span cases (§11); `messages`: how many turns it has (the Conversations overview); `owner_name`: a
 *  colleague's shared conversation, their name as the case knows it; `pinned`: a personal conversation its owner pinned
 *  in the sidebar (§3), one in a case follows its case; `run_id`: a playbook run's conversation, which opens the run and
 *  goes with its case; `titles`: a run's title in every language (the pack's words), of which listedTitle shows the
 *  reader's. */
export type ConversationSummary = gateway.ConversationSummary;
/** A conversation with its turns, as the gateway gives them back: the ones the server stored as it answered
 *  (suveryn-tracker#251), read into the chat UI's `Turn` (lib/conversations.ts, `savedConversation`). */
export type SavedConversation = Omit<gateway.Conversation, "turns"> & { turns: Turn[] };

/** A case (dossier), suveryn-tracker#10: the office's own file number as reference, never a client's
 *  name. `my_role`: what the signed-in user may do in it (null: an administrator who sees it exists).
 *  `keep_until`: a closed case, when it is deleted (null: kept until deleted by hand); `keep`: a closed case marked
 *  kept, never deleted by the period; `pinned`: in the signed-in user's sidebar (theirs alone; docs/design/chat-ui.md);
 *  `confidential`: strictly confidential (docs/design/chat-ui.md §11). */
export type Case = gateway.Case;
/** `access` default: as the office's default access; restricted: members only (board G14). */
export type NewCase = gateway.CaseIn;
/** A case type this appliance offers (suveryn-tracker#229): its id, the pack that brings it (core's reference content
 *  or an installed pack) and its word per language, from the pack. */
export type CaseTypeInfo = gateway.CaseTypeOut;
/** A case as the Cases overview shows it (docs/design/chat-ui.md §4): its members (the manager first)
 *  and its last activity, when and who. An administrator who isn't a member gets no members. */
export type CaseOverview = gateway.CaseOverview;
/** A member of a case, with the name as it was when they were added. */
export type Member = gateway.Member;
/** One of the office's accounts, from the directory (Keycloak), to add to a case. */
export type Person = gateway.Person;
/** One line of a case's access log: who did what, when (never document text). ``name``: who, as the case knows them
 *  or, for a deleted account, as it was called. */
export type CaseEvent = gateway.CaseEvent;
/** The administrator's pages (stage 4): every case with its manager, and the office's two case settings. */
export type AdminCase = gateway.AdminCase;
// conversations_keep: how long saved conversations are kept after their last change, in cases too (the data lifecycle, suveryn-tracker#31)
// two_step: every account must set up two-step sign-in (off by default; decision, 29 October 2026)
export type CaseSettings = gateway.SettingsOut;
/** What saving these settings would do now, for the confirmation in Administration › Settings: counts only. */
export type SettingsPreview = gateway.SettingsPreview;

/** Token counts (suveryn-tracker#7): counts only, never text. `totals_only_before`: the range reaches before the raw
 *  usage kept (24 months): before this, only the office's monthly totals. */
export type UsageTotals = gateway.UsageTotals;
export type UsageReport = gateway.UsageReport;
export type Rates = gateway.RatesOutput;
export type OfficeUsageReport = gateway.AdminUsageReport;

/** The appliance's backups (suveryn-tracker#33), as its backup service recorded them: the last one made and the last
 *  that failed (why, as a message of the registry, worded on the page), the administrator's last test of the recovery
 *  key, and where, when and how long as saved (never the share's password). */
export type BackupStatus = gateway.BackupStatus;
export type BackupSettings = gateway.BackupSettings;
export type BackupRetention = BackupSettings["retention_days"];
export type BackupDisk = gateway.Disk;

/** Administration › Status (docs/design/admin.md): a check, counts only. ``since``: when it was first seen
 *  failing, while it fails. */
export type StatusCheck = gateway.Check;
export type AdminStatus = gateway.AdminStatus;

/** The failure this file's calls throw for an answer that isn't the one asked for: signed out; the gateway's code
 *  with its words; or, for one that says it went well but isn't the gateway's (a proxy's or a hotel network's page,
 *  a body cut short or empty), the words of a part that isn't available. */
function failed({ data, status }: Answer): Error {
  if (status >= 200 && status < 300) return new HttpError(httpErrorText(502), status, problemOf(502, null));
  if (status === 401) { signedOutHandler(); return new SignedOut(); }
  const body = data !== null && typeof data === "object" ? data : null; // not JSON: a proxy's page
  return new HttpError(httpErrorText(status, body), status, problemOf(status, body));
}

/**
 * What a generated call (src/generated, from the gateway's description) answered, or the failure this file's other
 * calls throw. A call that never reached the gateway throws what `fetch` threw. An answer is read as JSON, or is
 * nothing where the gateway says it is done (204).
 */
export async function answered<A extends Answer>(call: Promise<A>): Promise<Extract<A, { status: 200 | 201 | 202 | 204 }>["data"]> {
  const answer = await call;
  const { data, status } = answer;
  if (status >= 200 && status < 300 && (data !== undefined || status === 204)) return data as Extract<A, { status: 200 | 201 | 202 | 204 }>["data"];
  throw failed(answer);
}

/** A generated call the gateway accepts with nothing to read (202: its result comes elsewhere, later), or the same
 *  failures. Only for an operation described that way: anywhere else an empty answer is not the gateway's. */
export async function accepted(call: Promise<Answer>): Promise<void> {
  const answer = await call;
  if (answer.status !== 202 || !answer.empty) throw failed(answer);
}

/** A generated removal: done, or already gone (404), which is the same to the screen; else the same failures.
 *  `also`: other statuses of that operation that mean the thing is gone as far as the screen is concerned. */
async function removed(call: Promise<Answer>, also: number[] = []): Promise<void> {
  const answer = await call;
  if (![204, 404, ...also].includes(answer.status)) throw failed(answer);
}

/** A query as a screen gives it to a generated call: a value is left out, never `null`, which Orval would write
 *  into the address as the word. */
type Asked<Query> = { [Name in keyof Query]?: NonNullable<Query[Name]> };

/** Administration › Backups: what the backup service recorded. */
export const getBackups = () => answered(gateway.getBackupStatus());

/** Test the recovery key: the key file as the web setup downloaded it. The appliance checks that it opens
 * the newest backup, restores nothing and deletes the key; getBackups() then has the result. */
export const testRecoveryKey = (keyFile: string): Promise<void> => accepted(gateway.testRecoveryKey(new Blob([keyFile])));

/** Ask the backup service (admin.md, artboard 36), then ask again every second until it has answered (at most
 *  ``seconds``). Why not, in its answer, as messages of the registry: one for the request, or one per field of the form. */
export async function askBackupService(body: gateway.BackupRequest, seconds = 60): Promise<gateway.RequestAnswer> {
  const { id } = await answered(gateway.createBackupRequest(body));
  for (let i = 0; i < seconds; i++) {
    await new Promise((done) => setTimeout(done, 1000));
    const answer = await answered(gateway.getBackupRequest(encodeURIComponent(id)));
    if (!answer.pending) return answer;
  }
  throw new Error(messageText({ kind: "unavailable", code: "backup.unavailable" }, t()));
}

/** Administration › Status (docs/design/admin.md): the six checks, counts only. */
export const getAdminStatus = () => answered(gateway.getApplianceStatus());

/** The models installed on this appliance, with which one is loaded and which is the default. */
export const listModels = () => answered(gateway.listModels());

// Without an end, the server ends the range at its own "now": the browser's clock may run behind
// the server's, and a range ending at the browser's "now" would miss the latest answers.
const range = (start: Date, end?: Date) => ({ start: start.toISOString(), ...(end ? { end: end.toISOString() } : {}) });

/** The signed-in user's own token usage between two moments. */
export const getMyUsage = (start: Date, end?: Date) => answered(gateway.getMyUsage(range(start, end)));

/** Administrators: the office's usage, per user, with the notional cloud cost. */
export const getOfficeUsage = (start: Date, end?: Date) => answered(gateway.getOfficeUsage(range(start, end)));

/** Administrators: the rates the notional cost uses, and changing them. */
export const getRates = () => answered(gateway.getUsageRates());
export const setRates = (rates: gateway.RatesInput) => answered(gateway.setUsageRates(rates));

/** Administrators: the office's settings as they apply now, what a change would do, and the change. */
export const getCaseSettings = () => answered(gateway.getOfficeSettings());
export const previewCaseSettings = (q: Asked<gateway.PreviewOfficeSettingsParams>) => answered(gateway.previewOfficeSettings(q));
/** ``apply_to``: when the access opens to the office, the existing cases too ("all") or only new ones ("new"). */
export const setCaseSettings = (changes: gateway.SettingsIn) => answered(gateway.updateOfficeSettings(changes));

/** Administrators: set the appliance's clock to this PC's time, by the difference just measured (lib/clock.ts). */
export const setApplianceClock = (measured: gateway.Measured) => answered(gateway.createClockRequest(measured));

/** The appliance's answer to that, or `pending` while it acts on it. Orval puts an id in the address as it is given. */
export const applianceClockAnswer = (id: string) => answered(gateway.getClockRequest(encodeURIComponent(id)));

/** Administration › Users (admin.md): the office's accounts through the gateway, never Keycloak's console.
 *  `last_sign_in_unknown`: no sign-in found, and the account is older than the 180 days of sign-ins Keycloak keeps. */
export type Account = gateway.Account;
export type UsersList = gateway.UsersOut;
/** A temporary password to pass on, in the answer once and nowhere else. */
export type TemporaryPassword = gateway.Temporary;
export type AccountEvent = gateway.AccountEvent;
/** Deleting an account (decision, 29 October): only once it is off. What would go, for the confirmation. */
export type AccountDeletion = gateway.Deletion;

export const listAccounts = () => answered(gateway.listAccounts());
export const addAccount = (name: string, email: string, admin: boolean) => answered(gateway.createAccount({ name, email, admin }));
export const setAccountAdmin = (sub: string, admin: boolean) => answered(gateway.setAccountAdmin(encodeURIComponent(sub), { admin }));
export const setAccountEnabled = (sub: string, enabled: boolean) => answered(gateway.setAccountEnabled(encodeURIComponent(sub), { enabled }));
export const resetAccountPassword = (sub: string) => answered(gateway.resetAccountPassword(encodeURIComponent(sub)));
export const resetAccountTwoStep = (sub: string): Promise<void> => answered(gateway.resetAccountTwoStep(encodeURIComponent(sub)));
export const signAccountOut = (sub: string): Promise<void> => answered(gateway.signOutAccount(encodeURIComponent(sub)));
export const accountDeletion = (sub: string) => answered(gateway.previewAccountDeletion(encodeURIComponent(sub)));
export const deleteAccount = (sub: string): Promise<void> => answered(gateway.deleteAccount(encodeURIComponent(sub)));
export const listAccountEvents = (limit: number) => answered(gateway.listAccountEvents({ limit }));

/** The names of deleted accounts, by id: what they did in the cases keeps their name. */
export const departedNames = () => answered(gateway.listDepartedUsers());

/** The office's accounts whose name or username contains `q`. */
export const searchUsers = (q: string) => answered(gateway.listUsers({ q }));




// ---------------------------------------------------------------- playbooks (suveryn-tracker#51, docs/design/playbooks.md)

/** A playbook that fits a case: its identity (id, pack, version) and whether this appliance may run it. `covered`:
 *  certified and in the appliance's manifest; false shows a warning, and the playbook still runs (never a block).
 *  `case_types` and `active`: the administration's list; an inactive playbook leaves every case's menu
 *  (docs/design/chat-ui.md). `lists`: per list fact, its entries' field ids ([] for a list of plain values), so the
 *  view can offer an entry to add. `kinds`: per fact and field (`founders.shares`): text, amount, date, number or
 *  choice. `choices`: per choice fact, its options. `text`: per language its title, one line on what it does, its fact
 *  labels and the routine's questions (the playbook carries them). `steps`: the routine (docs/design/playbooks.md,
 *  "The routine"), so the view can name the step a run is on. */
export type PlaybookInfo = gateway.PlaybookOut;
/** A step of the routine. `by`: who may pass a checkpoint, anyone who contributes to the case or its manager (the
 *  notary) only; `allow_none`: at a request, a person may answer that there is no such document. */
export type PlaybookStep = gateway.StepOut;
/** A value sūveryn worked out from another fact (suveryn_harness.terms): a date from a term, or an amount as a share
 *  of another. A term's `calendar`: for working days, the pack's calendar, its name per language. */
export type Computed = gateway.TermComputed | gateway.ShareComputed;
/** A fact of a run. `value`: as read, the model's from the documents or a person's answer to the playbook's question
 *  ("" when neither); `issues`: figures, dates or names the check couldn't find in the cited passages; `found` false:
 *  the documents don't contain it; `confirmed`: what the person confirmed at the checkpoint, once they have; `source`:
 *  where `value` came from; `by`, `at`: for a person's value, who gave it and when; `was`: for a correction of a value
 *  read from the documents, the value as read; `needs`: the value gives no date or amount as such, so a person works
 *  it out (`computed`: sūveryn did, from a term; board P01); `alternative`: a document added later reads this fact
 *  differently from what is confirmed, shown beside it, and a person chooses. */
export type RunFact = gateway.RunFact;
/** reading: the model is at work. waiting: for a person (a request, an ask, the checkpoint). paused, done, stopped,
 *  cancelled, failed: docs/design/playbooks.md, "A running playbook is visible". */
export type RunStatus = gateway.RunSummary["status"];
/** One line of the run's thread (the ``turns`` table): the playbook's turn, which is its meaning only (`meta`: its
 *  kind and facts, worded here in the reader's language), or a person's words and what came with them. */
export type RunTurn = gateway.RunTurn;
/** A run in a list. `failure`: why it failed, a code of the registry; `step`: the step it is on (null: not started, or
 *  ended); `language`: the thread's; `starter`: the starter's id, who may stop or cancel with the case manager;
 *  `title`: the playbook's title per language, for a chip anywhere; `conversation_id`: the run's conversation. */
export type RunSummary = gateway.RunSummary;
/** A run with its thread. `playbook`: the playbook it started under, from its own record (a run keeps its manifest);
 *  `requested`: per named request (step id), the documents that answered it; `checks`: per check step, its result on
 *  the values as they stand; `facts_seq`: which state of the facts this is, sent back when confirming. */
export type Run = gateway.Run;

// ---------------------------------------------------------------- avatars (docs/design/avatars.md)

/** Sets the caller's picture: the square the crop dialog made (PNG). The server re-encodes it; returns the new ETag. */
export const setMyAvatar = async (image: Blob): Promise<string> => (await answered(gateway.setMyPicture(image))).avatar;

/** Removes the caller's picture: their initials are shown again. */
export const removeMyAvatar = (): Promise<void> => answered(gateway.deleteMyPicture());

/** The cases (suveryn-tracker#244). The types this appliance offers. */
export const listCaseTypes = () => answered(gateway.listCaseTypes());
/** The cases the signed-in user may see, most recently active first: open ones, and with `closed` the closed ones too
 *  (after the open ones). */
export const listCases = (closed = false) => answered(gateway.listCases(closed ? { closed } : undefined));
/** Every case the signed-in user may see, open and closed, for the Cases overview. */
export const listCasesOverview = () => answered(gateway.listCaseOverviews());
/** Every case of the office with its manager, for the administrator's page. */
export const listAdminCases = () => answered(gateway.listOfficeCases());
export const createCase = (body: NewCase) => answered(gateway.createCase(body));
export const getCase = (id: string) => answered(gateway.getCase(encodeURIComponent(id)));
/** Changes a case's reference, name, type or access (its manager only). */
export const updateCase = (id: string, changes: gateway.CaseUpdate) => answered(gateway.updateCase(encodeURIComponent(id), changes));
/** Deletes a case with its documents and conversations (its manager only). */
export const deleteCase = (id: string) => removed(gateway.deleteCase(encodeURIComponent(id)));
/** Pins a case in the signed-in user's own sidebar, or unpins it (anyone who may read the case). */
export const pinCase = (id: string, pinned: boolean) => answered(gateway.setCasePinned(encodeURIComponent(id), { pinned }));
/** Closes a case (its manager only): read-only from then on, deleted after the office's keep period. */
export const closeCase = (id: string) => answered(gateway.closeCase(encodeURIComponent(id)));
/** Reopens a closed case (its manager only): open again, no deletion planned. */
export const reopenCase = (id: string) => answered(gateway.reopenCase(encodeURIComponent(id)));
/** A closed case's keep: `keep` true marks it kept (never deleted by the period), false lets the period run again from
 *  now; `extend` adds one period to its deletion date. Its manager, or an administrator. */
export const keepCase = (id: string, change: gateway.KeepIn) => answered(gateway.setCaseKeep(encodeURIComponent(id), change));
export const listMembers = (caseId: string) => answered(gateway.listCaseMembers(encodeURIComponent(caseId)));
/** Adds a colleague as a reader or contributor, or changes a member's role (the manager only). */
export const setMember = (caseId: string, user: string, role: "reader" | "contributor") =>
  answered(gateway.setCaseMember(encodeURIComponent(caseId), encodeURIComponent(user), { role }));
export const removeMember = (caseId: string, user: string) =>
  removed(gateway.removeCaseMember(encodeURIComponent(caseId), encodeURIComponent(user)));
/** Makes another colleague the case's manager (the manager, or an administrator). */
export const handOver = (caseId: string, user: string) => answered(gateway.handOverCase(encodeURIComponent(caseId), { user }));
/** The case's access log, newest first (its manager and the administrators). */
export const listCaseEvents = (caseId: string) => answered(gateway.listCaseEvents(encodeURIComponent(caseId)));

/** The conversations (suveryn-tracker#246). The signed-in user's saved conversations in the personal space, or in a
 *  case theirs and the shared ones, most recently changed first. */
export const listConversations = (caseId?: string | null) => answered(gateway.listConversations(caseId ? { case: caseId } : undefined));
/** The signed-in user's own conversations everywhere they may still look (their space and every case they may read),
 *  most recently changed first: the sidebar's "Conversations" (docs/design/chat-ui.md). */
export const listAllConversations = () => answered(gateway.listConversations({ all: true }));
export const getConversation = (id: string) => answered(gateway.getConversation(encodeURIComponent(id))) as Promise<SavedConversation>;
/** Renames one of the signed-in user's conversations, otherwise named after its first question (§4). */
export const renameConversation = (id: string, title: string) => answered(gateway.updateConversation(encodeURIComponent(id), { title }));
/** Pins one of the signed-in user's personal conversations in their sidebar, or unpins it (§3). */
export const pinConversation = (id: string, pinned: boolean) => answered(gateway.setConversationPinned(encodeURIComponent(id), { pinned }));
/** Moves one of the signed-in user's personal conversations into a case they contribute to (§4). It isn't shared and
 *  loses its own pin; its documents stay in the personal space. */
export const moveConversation = (id: string, caseId: string) => answered(gateway.moveConversation(encodeURIComponent(id), { case_id: caseId }));
/** Shares one of the signed-in user's conversations with its case, or stops sharing it (its owner only, open case). */
export const shareConversation = (id: string, shared: boolean) => answered(gateway.setConversationShared(encodeURIComponent(id), { shared }));
export const deleteConversation = (id: string) => removed(gateway.deleteConversation(encodeURIComponent(id)));
/** Deletes every saved conversation of the signed-in user (the sign-out choice "Delete history"). */
export const deleteAllConversations = async (): Promise<void> => { await answered(gateway.deleteMyConversations()); };

/** The playbooks (suveryn-tracker#247). The ones that fit a case. */
export const casePlaybooks = (caseId: string) => answered(gateway.listCasePlaybooks(encodeURIComponent(caseId)));
/** Administrators: every installed playbook, with whether it is switched on. */
export const listAdminPlaybooks = () => answered(gateway.listOfficePlaybooks());
/** Administrators: switch a playbook on or off for the whole office. */
export const setPlaybookActive = (slug: string, active: boolean) => answered(gateway.setPlaybookActive(encodeURIComponent(slug), { active }));
export const getRun = (caseId: string, runId: string) => answered(gateway.getRun(encodeURIComponent(caseId), encodeURIComponent(runId)));
/** The case's runs, newest first (a reader's right): the playbook menu's "Last" line (board P04, 9). */
export const caseRuns = (caseId: string) => answered(gateway.listCaseRuns(encodeURIComponent(caseId)));
/** The live run per case the caller may read (reading, waiting or paused), keyed by case id: the chip on the case lists. */
export const activeRuns = () => answered(gateway.listAllActiveRuns());
/** Starts a run (a contributor's right) in the thread's language and walks it to its first wait; 409 while one is live. */
export const startRun = (caseId: string, slug: string, language: string, documentIds: string[] = []) =>
  answered(gateway.startRun(encodeURIComponent(caseId), encodeURIComponent(slug), { document_ids: documentIds, language }));
/** Answers the step the run waits on: an ask's facts (a value per fact; empty: still unknown), or a request (the
 *  documents are in, or ``none`` when the step allows it). The answer goes into the thread and the run walks on. */
export const answerRun = (caseId: string, runId: string, stepId: string, answer: Omit<gateway.AnswerIn, "step_id"> = {}) =>
  answered(gateway.answerRun(encodeURIComponent(caseId), encodeURIComponent(runId), { step_id: stepId, ...answer }));
/** Writes in the run's conversation (a playbook is a conversation): the documents just added, an answer in words
 *  (mapped to the facts asked), ``unknown`` (the quick reply), or a correction at the checkpoint. The run walks on as
 *  far as it can. */
export const sayInRun = (caseId: string, runId: string, said: gateway.SayIn) =>
  answered(gateway.sayInRun(encodeURIComponent(caseId), encodeURIComponent(runId), said));
/** A value from a playbook's card at the checkpoint (Adjust, Fill in); the same value says the person checked it. */
export const setRunFact = (caseId: string, runId: string, factId: string, value: string) =>
  answered(gateway.setRunFact(encodeURIComponent(caseId), encodeURIComponent(runId), encodeURIComponent(factId), { value }));
/** Pause (keeps everything), resume, stop (keeps confirmed facts, drops proposed ones) or cancel (reverts confirmed
 *  facts, withdraws the product). Pause and resume: anyone who contributes; stop and cancel: the starter or the case
 *  manager. */
export const runAction = (caseId: string, runId: string, action: "pause" | "resume" | "stop" | "cancel", reason = "") => {
  const run = encodeURIComponent(runId);
  return answered(action === "pause" ? gateway.pauseRun(encodeURIComponent(caseId), run) : action === "resume" ? gateway.resumeRun(encodeURIComponent(caseId), run)
    : action === "stop" ? gateway.stopRun(encodeURIComponent(caseId), run) : gateway.cancelRun(encodeURIComponent(caseId), run, { reason }));
};
/** The checkpoint: every fact's confirmed value; the summary is then stored in the case as a document. `seen` is the
 *  state of the facts on this screen (`Run.facts_seq`): when a colleague changed one since, the server refuses (409,
 *  `run.facts_changed`) and writes nothing, so an old screen can't put a value back (suveryn-tracker#135). */
export const confirmRun = (caseId: string, runId: string, facts: gateway.ConfirmedFact[], seen?: number) =>
  answered(gateway.confirmRunFacts(encodeURIComponent(caseId), encodeURIComponent(runId), { facts, seen }));

/** The documents (suveryn-tracker#248). The documents in the personal space, or in a case, and the uploads there
 *  still being read or failed. */
export const listDocuments = (caseId?: string | null) => answered(gateway.listDocuments(inCase(caseId)));
/** Every document the signed-in user may see, with where it is (`case_id` null: the personal space), newest first:
 *  the sidebar's "Documents" (docs/design/chat-ui.md). */
export const listAllDocuments = async () => (await answered(gateway.listAllDocuments())).documents;
export const getJob = (id: string) => answered(gateway.getUpload(encodeURIComponent(id)));
/** Cancels an upload still waiting or being read (docs/design/chat-ui.md §5). One already read is a document (409)
 *  and one unknown is gone (404): both are fine to ignore here. */
export const cancelJob = (id: string) => removed(gateway.cancelUpload(encodeURIComponent(id)), [409]);
/** Deletes a document. Saved conversations citing it lose its passages ("clean") or are deleted too. Deleted with
 *  that cleaning still to be done (202) is deleted. */
export const deleteDocument = (id: string, conversations: "clean" | "delete" = "clean", caseId?: string | null) =>
  removed(gateway.deleteDocument(encodeURIComponent(id), { conversations, ...inCase(caseId) }), [202]);
/** The saved conversations that cite or attach a document (asked before deleting it). */
export const documentConversations = (id: string, caseId?: string | null) =>
  answered(gateway.listDocumentConversations(encodeURIComponent(id), inCase(caseId)));
/** Use an upload that carries sūveryn's own export mark as a source anyway (docs/design/chat-ui.md §6). */
export const confirmAsSource = async (documentId: string, caseId?: string | null): Promise<void> => {
  await answered(gateway.useDocumentAsSource(encodeURIComponent(documentId), inCase(caseId)));
};
/** An answer the server stored, saved to its conversation's case (docs/design/chat-ui.md §5): the server copies it as it
 *  was written (suveryn-tracker#251), a document with origin answer, never a source, its content in the shape of
 *  `SavedAnswer`. Saving the same answer again gives the document already saved (`created` false). */
export const saveTurnAsDocument = (conversationId: string, seq: number) =>
  answered(gateway.saveTurnAsDocument(encodeURIComponent(conversationId), seq));
/** What rebuilds a document sūveryn made (a saved answer's Word file). */
export const documentContent = (documentId: string, caseId?: string | null) =>
  answered(gateway.getDocumentContent(encodeURIComponent(documentId), inCase(caseId))) as
    Promise<Omit<gateway.DocumentContent, "content"> & { content: SavedAnswer }>;

