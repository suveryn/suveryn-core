/**
 * The gateway API, as used by the UI. All calls are relative (same origin); in development Vite
 * proxies them to the gateway. No other host is ever contacted.
 */
import { clearDraft } from "./lib/draft";
import { createSSEParser } from "./lib/sse";
import { lang, t } from "./i18n";
import type { Turn } from "./types";
import type { SavedAnswer } from "./lib/saved";

type SourceRef = { document_id: string; page: number | null; location: string | null };
/** ``removed``: its document was deleted, so the passage was taken out (suveryn-tracker#12). */
export type Citation = { text: string; source: SourceRef | null; removed?: boolean };
/** A fact in a cited claim that the cited passage doesn't contain (suveryn-tracker#11). ``marker`` is the
 *  0-based place of the [n] among the answer's valid markers; ``found_in``: other passages that do contain it. */
export type CitationIssue = { marker: number; n: number; item: string; found_in: number[]; written_as: string | null };
/** A calculation the server computed exactly; the model only chose the figures. */
export type Calculation = {
  expression: string;
  result: string | null;              // null: it couldn't be computed (see error)
  figures_not_in_sources: string[];   // figures to check: they don't appear in the passages given
  error: string | null;
};
export type ChatResponse = {
  id: string;
  model: string;
  answer: string;
  citations: Citation[];
  calculations: Calculation[];
  unverified_figures?: string[];      // figures in no passage and no calculation's result: flag them for checking
  citation_issues?: CitationIssue[];  // facts the cited passage doesn't contain: flag the marker
  instruction_like_sources?: number[]; // passages whose text addresses an AI: tell the reader (suveryn-tracker#21)
  finish_reason: string | null;
  reasoning?: string;              // *Thorough*: what the model thought before answering, never in ``answer``
  thought_seconds?: number | null; // and for how long
};
export type WireMessage = { role: "user" | "assistant" | "system"; content: string };

export type JobStatus = "queued" | "processing" | "ready" | "needs_review" | "failed" | "cancelled";
/** How far reading has got (suveryn_rag.reading.Progress): text recognition page by page, the layout, storing. */
export type JobProgress = { step: "read" | "ocr" | "layout" | "store"; done: number | null; total: number | null };
export type Warning = { page: number | null; kind: string; detail: string };
export type Job = {
  id: string; filename: string; status: JobStatus; document_id: string | null; error?: string | null; warnings?: Warning[];
  pages?: number | null;
  progress?: JobProgress | null;
  error_code?: string | null;              // why it failed (suveryn_rag.reading.CODES), for the interface to say
  error_detail?: Record<string, number>;   // the numbers that needs: pages, max, minutes
  noticed?: Noticed | null;  // the file carries sūveryn's own export mark: not a source until someone says so
};
/** sūveryn's export mark found in an upload (docs/design/sidebar.md §6): the line as it stands in the file. */
export type Noticed = { ref: string; kind: "answer" | "playbook"; line: string };
/** More about where a document came from (docs/design/sidebar.md §6). */
export type Provenance = {
  playbook?: string; version?: string; run?: string;               // a playbook's result
  noticed?: Noticed; confirmed?: { by: string; at: string };      // an upload that looked like sūveryn's own output
};
export type StoredDocument = {
  id: string;
  filename: string;
  pages: number;
  ocr_pages: number;
  status: "ok" | "needs_review";
  warnings: Warning[];
  created_at: string;
  chunks: number;
  origin?: "uploaded" | "generated" | "playbook" | "answer"; // only uploaded documents are sources for answers (suveryn-tracker#10)
  uploaded_by?: string | null;
  source?: boolean;               // the model may read and cite it (cases.md decision 7; the server decides)
  provenance?: Provenance | null;
};
export type Health = {
  status: "ok" | "degraded";
  backend: { reachable: boolean; status: string; model: string | null };
  documents: { status: "ready" | "starting" | "failed" | "unavailable"; detail: string | null };
  auth: { status: "ready" | "unavailable" | "not_configured" | "disabled"; detail: string | null };
  history: { status: "ready" | "failed" | "unavailable"; detail: string | null };
  cases?: { status: "ready" | "failed" | "unavailable"; detail: string | null };
  directory?: { status: "ready" | "unavailable"; detail: string | null };
};
// admin: may open the administration page; office_wide: a new case is open to the whole office by
// default; cases_keep: how long a closed case is kept before it is deleted ("manual": until deleted by hand)
export type KeepPeriod = "6m" | "1y" | "5y" | "manual";
// avatar: the ETag of the user's picture (null: initials are shown); see Avatar in the UI kit
// account_url: where the person changes their password (Keycloak's account console); null with sign-in off
export type Me = { username: string; name: string; sub?: string; admin?: boolean; office_wide?: boolean; cases_keep?: KeepPeriod; avatar?: string | null;
                   account_url?: string | null };
/** A pipeline step the server reports before the answer's first word (SSE event `status`). */
export type StreamStatus = {
  step: "searching" | "loading_model" | "reading" | "writing" | "thinking";
  passages: number | null;
  complete: boolean | null;
  model: string | null;
};
/** An installed model (GET /v1/models); only one is in GPU memory at a time. */
// thinks: the model can think before it answers, so *Thorough* is possible (docs/design/sidebar.md §5)
export type ModelInfo = { id: string; loaded: boolean; default: boolean; thinks?: boolean };

/** The models installed on this appliance, with which one is loaded and which is the default. */
export async function listModels(): Promise<ModelInfo[]> {
  const r = await fetch("/v1/models");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/**
 * Sign-in. The gateway runs the OIDC login with Keycloak and keeps the tokens; the browser only
 * holds an HttpOnly session cookie that fetch and XHR send automatically (same origin). A 401 from
 * any API call means the session ended: the registered handler shows the sign-in screen.
 */
class SignedOut extends Error {
  constructor() { super(t().sessionEndedError); }
}
let signedOutHandler: () => void = () => {};
export function onSignedOut(handler: () => void): void { signedOutHandler = handler; }

/** A refused request: its sentence for the person, and the status, for a page that acts on it. */
export class HttpError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

async function responseError(r: Response): Promise<Error> {
  if (r.status === 401) { signedOutHandler(); return new SignedOut(); }
  return new HttpError(await errorText(r), r.status);
}

/** The signed-in user, or null if signed out. Throws if sign-in itself is unavailable. */
export async function getMe(): Promise<Me | null> {
  const r = await fetch("/auth/me");
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

/** Goes to the Keycloak login page (through the gateway); comes back to the chat. */
export function signIn(): void {
  window.location.assign(`/auth/login?return_to=/&lang=${lang()}`);
}

/** Ends the session in the gateway, then in Keycloak (its logout page sends the browser back). */
export async function signOut(): Promise<void> {
  clearDraft();  // a question typed but not sent doesn't outlive the session on this computer
  let url: string | null = null;
  try {
    const r = await fetch("/auth/logout", { method: "POST" });
    url = (await r.json()).logout_url ?? null;
  } catch { /* the session is dropped anyway when it expires */ }
  window.location.assign(url ?? "/");
}

/**
 * What went wrong, in the interface's language: by HTTP status for the errors a user meets (the server's
 * own text is English, and a validation error's detail is a list, which showed as "HTTP 422"). Other
 * statuses keep the server's text.
 */
export function httpErrorText(status: number, detail: unknown, retryAfter: string | null = null, reason: unknown = null): string {
  const m = t();
  switch (status) {
    case 429: return m.tooManyRequests(retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) : null);
    case 413: return typeof detail === "string" && /conversation/i.test(detail) ? m.conversationTooLong : m.fileTooLarge;
    case 415: return m.fileNotSupported;
    case 422: return m.requestRejected;
    case 404: return m.notFound;
    case 403: return m.forbidden;
    // ``reason`` (the gateway's 503s): which part is down, so the person reads what it is.
    case 502: case 503: return reason === "database" ? m.databaseUnavailable : reason === "signin" ? m.signInServiceUnavailable : m.serverUnavailable;
    default: return typeof detail === "string" ? detail : `HTTP ${status}`;
  }
}

async function errorText(r: Response): Promise<string> {
  let detail: unknown = null;
  let reason: unknown = null;
  try { ({ detail, reason } = await r.json()); } catch { /* no JSON body */ }
  return httpErrorText(r.status, detail, r.headers.get("Retry-After"), reason);
}

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch("/health");
    return (await r.json()) as Health; // 503 still carries a body
  } catch {
    return null; // gateway not reachable
  }
}

/** `?case=<id>` on a request about a case; nothing for the personal space (suveryn-tracker#10). */
const inCase = (caseId: string | null | undefined, first = true) =>
  caseId ? `${first ? "?" : "&"}case=${encodeURIComponent(caseId)}` : "";

/** Use an upload that carries sūveryn's own export mark as a source anyway (docs/design/sidebar.md §6). */
export async function confirmAsSource(documentId: string, caseId?: string | null): Promise<void> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(documentId)}/source${inCase(caseId)}`, { method: "POST" });
  if (!r.ok) throw await responseError(r);
}

/** An answer saved to its case (docs/design/sidebar.md §5): a document with origin answer, never a source.
 *  Saving the same answer again gives the document already saved (`created` false). */
export async function saveAnswerToCase(caseId: string, body: {
  filename: string; text: string; content: SavedAnswer; conversation_id: string; message_id: string;
}): Promise<{ id: string; filename: string; created: boolean }> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/documents`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** What rebuilds a document sūveryn made (a saved answer's Word file). */
export async function documentContent(documentId: string, caseId?: string | null): Promise<{ filename: string; origin: string; content: SavedAnswer }> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(documentId)}/content${inCase(caseId)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Every document the signed-in user may see, with where it is (`case_id` null: the personal space),
 *  newest first: the sidebar's "Documents" (docs/design/sidebar.md). */
export async function listAllDocuments(): Promise<(StoredDocument & { case_id: string | null })[]> {
  const r = await fetch("/v1/documents/all");
  if (!r.ok) throw await responseError(r);
  return (await r.json()).documents;
}

/** The documents in the personal space, or in a case. */
export async function listDocuments(caseId?: string | null): Promise<{ documents: StoredDocument[]; jobs: Job[] }> {
  const r = await fetch(`/v1/documents${inCase(caseId)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/**
 * Uploads a document (PDF, Word, Excel, Markdown or CSV: lib/formats.ts) and resolves with its job. Uses XMLHttpRequest rather than fetch because only
 * XHR reports upload progress; `onProgress` gets a fraction from 0 to 1.
 */
export function uploadDocument(file: File, onProgress?: (fraction: number) => void, caseId?: string | null,
                               signal?: AbortSignal): Promise<Job> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/v1/documents${inCase(caseId)}`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Job);
      else if (xhr.status === 401) { signedOutHandler(); reject(new SignedOut()); }
      else reject(new Error(httpErrorText(xhr.status, xhr.response?.detail, xhr.getResponseHeader("Retry-After"), xhr.response?.reason)));
    };
    xhr.onerror = () => reject(new Error(t().uploadInterrupted));
    xhr.onabort = () => reject(new DOMException("cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`/v1/documents/jobs/${encodeURIComponent(id)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Cancels an upload still waiting or being read (docs/design/sidebar.md §5). One already read is a
 *  document (409) and one unknown is gone (404): both are fine to ignore here. */
export async function cancelJob(id: string): Promise<void> {
  const r = await fetch(`/v1/documents/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404 && r.status !== 409) throw await responseError(r);
}

/** Deletes a document. Saved conversations citing it lose its passages ("clean") or are deleted too. */
export async function deleteDocument(id: string, conversations: "clean" | "delete" = "clean", caseId?: string | null): Promise<void> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(id)}?conversations=${conversations}${inCase(caseId, false)}`,
                        { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw await responseError(r);
}

/** The saved conversations that cite or attach a document (asked before deleting it). */
export async function documentConversations(id: string, caseId?: string | null): Promise<ConversationSummary[]> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(id)}/conversations${inCase(caseId)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/**
 * Streams an answer. Calls `onDelta` with each piece of text, then resolves with the complete
 * answer (including citations). Rejects if the stream ends in an `error` event or breaks off;
 * any partial text must then be discarded (gateway contract).
 */
export async function streamChat(
  messages: WireMessage[],
  documentIds: string[],
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  model?: string | null,          // an id from listModels(); null or undefined: the default model
  onStatus?: (status: StreamStatus) => void,
  caseId?: string | null,         // the case the documents are in; null or undefined: the personal space
  onSources?: (citations: Citation[]) => void,  // a grounded answer's passages, before its first word
  thinking?: { on: boolean; onText: (text: string) => void },  // *Thorough*: think first; the reasoning as it comes
): Promise<ChatResponse> {
  const r = await fetch("/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, document_ids: documentIds, stream: true, max_tokens: 1500, ...(model ? { model } : {}),
                           ...(caseId ? { case_id: caseId } : {}), ...(thinking?.on ? { thinking: true } : {}) }),
    signal,
  });
  if (!r.ok || !r.body) throw await responseError(r);
  let done: ChatResponse | null = null;
  let failure: string | null = null;
  const parser = createSSEParser(({ event, data }) => {
    const payload = JSON.parse(data);
    if (event === "status") onStatus?.(payload as StreamStatus);
    else if (event === "sources") onSources?.(payload.citations as Citation[]);
    else if (event === "thinking") thinking?.onText(payload.text);
    else if (event === "delta") onDelta(payload.text);
    else if (event === "done") done = payload as ChatResponse;
    else if (event === "error") failure = payload.message ?? "unknown error";
  });
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done: finished } = await reader.read();
    if (finished) break;
    parser.feed(value);
  }
  if (failure) throw new Error(failure);
  if (!done) throw new Error(t().streamCutOff);
  return done;
}

/** Pages where text may be missing (the warnings that put a document in needs_review). */
export function reviewPages(warnings: Warning[] | undefined): number[] {
  const pages = (warnings ?? []).filter((w) => (w.kind === "page_coverage_low" || w.kind === "layout_failed") && w.page !== null).map((w) => w.page!);
  return [...new Set(pages)].sort((a, b) => a - b);
}

/** A saved conversation in the list (GET /v1/conversations): no content, newest first. */
// owner: who started it (a Keycloak id); shared: shared with the case's members (stage 4), read-only for them
export type ConversationSummary = {
  id: string; title: string | null; created_at: string; updated_at: string; case_id?: string | null; owner?: string; shared?: boolean;
  shielded?: boolean;  // in a strictly confidential case: no title in the lists that span cases (§11)
  messages?: number;    // how many turns it has (the Conversations overview)
  owner_name?: string;  // a colleague's shared conversation: their name as the case knows it
  pinned?: boolean;     // a personal conversation its owner pinned in the sidebar (§3); one in a case follows its case
};
export type SavedConversation = ConversationSummary & { turns: Turn[] };

/** Renames one of the signed-in user's conversations; the title is kept over later saves (§4). */
export async function renameConversation(id: string, title: string): Promise<ConversationSummary> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Pins one of the signed-in user's personal conversations in their sidebar, or unpins it (§3). */
export async function pinConversation(id: string, pinned: boolean): Promise<ConversationSummary> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}/pin`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pinned }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Moves one of the signed-in user's personal conversations into a case they contribute to (§4). It
 *  isn't shared and loses its own pin; its documents stay in the personal space. */
export async function moveConversation(id: string, caseId: string): Promise<ConversationSummary> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}/move`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Shares one of the signed-in user's conversations with its case, or stops sharing it (its owner only, open case). */
export async function shareConversation(id: string, shared: boolean): Promise<ConversationSummary> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}/share`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shared }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The signed-in user's saved conversations in the personal space, or in a case theirs and the shared ones, most recently changed first. */
export async function listConversations(caseId?: string | null): Promise<ConversationSummary[]> {
  const r = await fetch(`/v1/conversations${inCase(caseId)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The signed-in user's own conversations everywhere they may still look (their space and every case
 *  they may read), most recently changed first: the sidebar's "Conversations" (docs/design/sidebar.md). */
export async function listAllConversations(): Promise<ConversationSummary[]> {
  const r = await fetch("/v1/conversations?all=true");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function getConversation(id: string): Promise<SavedConversation> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Saves the whole conversation, replacing an earlier save under the same id. A new conversation goes
 *  into the case `caseId` (or the personal space); a saved one stays where it was first saved. */
export async function saveConversation(id: string, title: string, turns: Turn[], caseId?: string | null): Promise<void> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, turns, ...(caseId ? { case_id: caseId } : {}) }),
  });
  if (!r.ok) throw await responseError(r);
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`/v1/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw await responseError(r);
}

/** Deletes every saved conversation of the signed-in user (the sign-out choice "Delete history"). */
export async function deleteAllConversations(): Promise<void> {
  const r = await fetch("/v1/conversations", { method: "DELETE" });
  if (!r.ok) throw await responseError(r);
}

/** A case (dossier), suveryn-tracker#10: the office's own file number as reference, never a client's
 *  name. `my_role`: what the signed-in user may do in it (null: an administrator who sees it exists). */
export type CaseRole = "reader" | "contributor" | "manager";
export type Case = {
  id: string;
  reference: string;
  name: string;
  type: string;
  subject: Record<string, unknown>;
  access: "default" | "restricted";
  state: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  keep_until: string | null;  // a closed case: when it is deleted (null: kept until deleted by hand)
  keep: boolean;              // a closed case marked kept: never deleted by the period
  manager: string;
  created_by: string;
  updated_at: string;
  my_role: CaseRole | null;
  pinned?: boolean;           // in the signed-in user's sidebar (theirs alone; docs/design/sidebar.md)
  confidential?: boolean;     // strictly confidential (docs/design/sidebar.md §11)
};
export type NewCase = { reference: string; name: string; type: string; subject: Record<string, string> };

/** The cases the signed-in user may see, most recently active first: open ones, and with
 *  `closed` the closed ones too (after the open ones). */
export async function listCases(closed = false): Promise<Case[]> {
  const r = await fetch(`/v1/cases${closed ? "?closed=true" : ""}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** A case as the Cases overview shows it (docs/design/sidebar.md §4): its members (the manager first)
 *  and its last activity, when and who. An administrator who isn't a member gets no members. */
export type CaseOverview = Case & { members: Member[]; last_activity_at: string | null; last_activity_by: string };

/** Every case the signed-in user may see, open and closed, for the Cases overview. */
export async function listCasesOverview(): Promise<CaseOverview[]> {
  const r = await fetch("/v1/cases/overview");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Pins a case in the signed-in user's own sidebar, or unpins it (anyone who may read the case). */
export async function pinCase(id: string, pinned: boolean): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}/pin`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pinned }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function createCase(body: NewCase): Promise<Case> {
  const r = await fetch("/v1/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function getCase(id: string): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Changes a case's reference, name, type, subject or access (its manager only). */
export async function updateCase(id: string, changes: Partial<NewCase> & { access?: Case["access"]; confidential?: boolean }): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** A member of a case, with the name as it was when they were added. */
export type Member = { user: string; username: string; name: string; role: CaseRole; added_by: string; added_at: string; admin?: boolean; avatar?: string | null };
/** One of the office's accounts, from the directory (Keycloak), to add to a case. */
export type Person = { sub: string; username: string; name: string; admin?: boolean; avatar?: string | null };
/** One line of a case's access log: who did what, when (never document text). */
export type CaseEvent = { id: number; user: string; at: string; action: string; detail: Record<string, unknown> };

export async function listMembers(caseId: string): Promise<Member[]> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/members`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Adds a colleague as a reader or contributor, or changes a member's role (the manager only). */
export async function setMember(caseId: string, user: string, role: "reader" | "contributor"): Promise<Member> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/members/${encodeURIComponent(user)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function removeMember(caseId: string, user: string): Promise<void> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/members/${encodeURIComponent(user)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw await responseError(r);
}

/** Makes another colleague the case's manager (the manager, or an administrator). */
export async function handOver(caseId: string, user: string): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/handover`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The office's accounts whose name or username contains `q`. */
export async function searchUsers(q: string): Promise<Person[]> {
  const r = await fetch(`/v1/users?q=${encodeURIComponent(q)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The case's access log, newest first (its manager and the administrators). */
export async function listCaseEvents(caseId: string): Promise<CaseEvent[]> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/events`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Closes a case (its manager only): read-only from then on, deleted after the office's keep period. */
export async function closeCase(id: string): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}/close`, { method: "POST" });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Reopens a closed case (its manager only): open again, no deletion planned. */
export async function reopenCase(id: string): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}/reopen`, { method: "POST" });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** A closed case's keep: `keep` true marks it kept (never deleted by the period), false lets the
 *  period run again from now; `extend` adds one period to its deletion date. Its manager, or an
 *  administrator. */
export async function keepCase(id: string, change: { keep?: boolean; extend?: boolean }): Promise<Case> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}/keep`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Closed cases due for deletion within a month, soonest first: the ones the signed-in user
 *  manages, or every one for an administrator. */
export async function listDueCases(): Promise<Case[]> {
  const r = await fetch("/v1/cases/due");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The administrator's pages (stage 4): every case with its manager, and the office's two case settings. */
export type AdminCase = Case & { manager_username: string; manager_name: string; members: number };
// conversations_keep: how long saved conversations are kept after their last change, in cases too (the data lifecycle, suveryn-tracker#31)
export type CaseSettings = { default_access: "office" | "members"; keep: KeepPeriod; conversations_keep: KeepPeriod; updated_at: string | null; updated_by: string };

export async function listAdminCases(): Promise<AdminCase[]> {
  const r = await fetch("/v1/admin/cases");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function getCaseSettings(): Promise<CaseSettings> {
  const r = await fetch("/v1/admin/cases/settings");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function setCaseSettings(changes: Partial<Pick<CaseSettings, "default_access" | "keep" | "conversations_keep">>): Promise<CaseSettings> {
  const r = await fetch("/v1/admin/cases/settings", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Deletes a case with its documents and conversations (its manager only). */
export async function deleteCase(id: string): Promise<void> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw await responseError(r);
}

/** Token counts (suveryn-tracker#7): counts only, never text. */
export type UsageTotals = { requests: number; prompt_tokens: number; completion_tokens: number; total_tokens: number };
export type UsageReport = {
  start: string; end: string;
  step: "5 minutes" | "1 hour" | "1 day" | "7 days" | "30 days";
  totals: UsageTotals;
  series: (UsageTotals & { start: string })[];
  by_kind: Record<string, UsageTotals>;
  /** The range reaches before the raw usage kept (24 months): before this, only the office's monthly totals. */
  totals_only_before?: string | null;
};
export type Rates = { input_per_million: string; output_per_million: string; currency: string; updated_at?: string | null; updated_by?: string | null };
type UserUsage = { user_id: string; username: string | null; name: string | null; totals: UsageTotals; cost: string | null };
export type OfficeUsageReport = UsageReport & { per_user: UserUsage[]; rates: Rates; cost: string };

// Without an end, the server ends the range at its own "now": the browser's clock may run behind
// the server's, and a range ending at the browser's "now" would miss the latest answers.
const range = (start: Date, end?: Date) =>
  `start=${encodeURIComponent(start.toISOString())}${end ? `&end=${encodeURIComponent(end.toISOString())}` : ""}`;

/** The signed-in user's own token usage between two moments. */
export async function getMyUsage(start: Date, end?: Date): Promise<UsageReport> {
  const r = await fetch(`/v1/usage?${range(start, end)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Administrators: the office's usage, per user, with the notional cloud cost. */
export async function getOfficeUsage(start: Date, end?: Date): Promise<OfficeUsageReport> {
  const r = await fetch(`/v1/admin/usage?${range(start, end)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Administrators: change the rates the notional cost uses. */
export async function setRates(rates: Pick<Rates, "input_per_million" | "output_per_million" | "currency">): Promise<Rates> {
  const r = await fetch("/v1/admin/usage/rates", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rates),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

// ---------------------------------------------------------------- playbooks (suveryn-tracker#51, docs/design/playbooks.md)

/** A playbook that fits a case: its identity (id, pack, version) and whether this appliance may run it. */
/** covered: certified and in the appliance's manifest; false shows a warning, and the playbook still runs (never a block). */
/** case_types and active: the administration's list; an inactive playbook leaves every case's menu (docs/design/sidebar.md). */
export type PlaybookInfo = { id: string; slug: string; pack: string; version: string; name: string; covered: boolean; facts: string[];
                             case_types?: string[]; active?: boolean;
                             /** Per language: its title, one line on what it does, its fact labels (the playbook carries them). */
                             text?: Record<string, { title: string; summary: string; labels: Record<string, string> }> };
/** A passage a fact was read from, kept with the run (so it can be shown after the document is deleted). */
export type FactCitation = { n: number; document_id: string; filename: string; page: number | null; location: string | null; text: string };
export type RunFact = {
  id: string;
  value: string;              // as the model read it, copied from the documents ("" when not found)
  citations: FactCitation[];
  issues: string[];           // figures, dates or names the check couldn't find in the cited passages
  found: boolean;             // false: the documents don't contain it
  confirmed: string | null;   // what the person confirmed, once they have
};
export type RunStatus = "reading" | "checkpoint" | "confirmed" | "failed";
export type RunSummary = {
  id: string; case_id: string; playbook_id: string; playbook_version: string; status: RunStatus; documents: string[];
  started_by: string; started_at: string; finished_at: string | null; confirmed_by: string | null; confirmed_at: string | null;
  model: string | null; error: string | null; result_document_id: string | null; out_of_date: boolean;
};
export type Run = RunSummary & { facts: RunFact[]; instruction_like_sources: number[] };

export async function casePlaybooks(caseId: string): Promise<PlaybookInfo[]> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/playbooks`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Administrators: every installed playbook, with whether it is switched on. */
export async function listAdminPlaybooks(): Promise<PlaybookInfo[]> {
  const r = await fetch("/v1/admin/playbooks");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Administrators: switch a playbook on or off for the whole office. */
export async function setPlaybookActive(slug: string, active: boolean): Promise<PlaybookInfo> {
  const r = await fetch(`/v1/admin/playbooks/${encodeURIComponent(slug)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function listRuns(caseId: string): Promise<RunSummary[]> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/playbooks/runs`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function getRun(caseId: string, runId: string): Promise<Run> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/playbooks/runs/${encodeURIComponent(runId)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** Starts a run (a contributor's right): it reads the case's uploaded documents; poll the run until it reaches the checkpoint. */
export async function startRun(caseId: string, slug: string, documentIds: string[] = []): Promise<Run> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/playbooks/${encodeURIComponent(slug)}/runs`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_ids: documentIds }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/** The checkpoint: every fact's confirmed value; the summary is then stored in the case as a document. */
export async function confirmRun(caseId: string, runId: string, facts: { id: string; confirmed: string }[], language: string): Promise<Run> {
  const r = await fetch(`/v1/cases/${encodeURIComponent(caseId)}/playbooks/runs/${encodeURIComponent(runId)}/facts`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facts, language }),
  });
  if (!r.ok) throw await responseError(r);
  return r.json();
}

// ---------------------------------------------------------------- avatars (docs/design/avatars.md)

/** Sets the caller's picture: the square the crop dialog made (PNG). The server re-encodes it; returns the new ETag. */
export async function setMyAvatar(image: Blob): Promise<string> {
  const r = await fetch("/v1/me/avatar", { method: "PUT", headers: { "Content-Type": image.type || "image/png" }, body: image });
  if (!r.ok) throw await responseError(r);
  return (await r.json()).avatar as string;
}

/** Removes the caller's picture: their initials are shown again. */
export async function removeMyAvatar(): Promise<void> {
  const r = await fetch("/v1/me/avatar", { method: "DELETE" });
  if (!r.ok) throw await responseError(r);
}
