/**
 * The gateway API, as used by the UI. All calls are relative (same origin); in development Vite
 * proxies them to the gateway. No other host is ever contacted.
 */
import { createSSEParser } from "./lib/sse";

export type SourceRef = { document_id: string; page: number | null; location: string | null };
export type Citation = { text: string; source: SourceRef | null };
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
  finish_reason: string | null;
};
export type WireMessage = { role: "user" | "assistant" | "system"; content: string };

export type JobStatus = "queued" | "processing" | "ready" | "needs_review" | "failed";
export type Warning = { page: number | null; kind: string; detail: string };
export type Job = {
  id: string; filename: string; status: JobStatus; document_id: string | null; error?: string | null; warnings?: Warning[];
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
};
export type Health = {
  status: "ok" | "degraded";
  backend: { reachable: boolean; status: string; model: string | null };
  documents: { status: "ready" | "starting" | "failed" | "unavailable"; detail: string | null };
  auth: { status: "ready" | "unavailable" | "not_configured" | "disabled"; detail: string | null };
};
export type Me = { username: string; name: string };

/**
 * Sign-in. The gateway runs the OIDC login with Keycloak and keeps the tokens; the browser only
 * holds an HttpOnly session cookie that fetch and XHR send automatically (same origin). A 401 from
 * any API call means the session ended: the registered handler shows the sign-in screen.
 */
export class SignedOut extends Error {
  constructor() { super("your session has ended; sign in again"); }
}
let signedOutHandler: () => void = () => {};
export function onSignedOut(handler: () => void): void { signedOutHandler = handler; }

async function responseError(r: Response): Promise<Error> {
  if (r.status === 401) { signedOutHandler(); return new SignedOut(); }
  return new Error(await errorText(r));
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
  window.location.assign("/auth/login?return_to=/");
}

/** Ends the session in the gateway, then in Keycloak (its logout page sends the browser back). */
export async function signOut(): Promise<void> {
  let url: string | null = null;
  try {
    const r = await fetch("/auth/logout", { method: "POST" });
    url = (await r.json()).logout_url ?? null;
  } catch { /* the session is dropped anyway when it expires */ }
  window.location.assign(url ?? "/");
}

async function errorText(r: Response): Promise<string> {
  try {
    const body = await r.json();
    return typeof body.detail === "string" ? body.detail : `HTTP ${r.status}`;
  } catch {
    return `HTTP ${r.status}`;
  }
}

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch("/health");
    return (await r.json()) as Health; // 503 still carries a body
  } catch {
    return null; // gateway not reachable
  }
}

export async function listDocuments(): Promise<{ documents: StoredDocument[]; jobs: Job[] }> {
  const r = await fetch("/v1/documents");
  if (!r.ok) throw await responseError(r);
  return r.json();
}

/**
 * Uploads a PDF and resolves with its job. Uses XMLHttpRequest rather than fetch because only
 * XHR reports upload progress; `onProgress` gets a fraction from 0 to 1.
 */
export function uploadDocument(file: File, onProgress?: (fraction: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/v1/documents");
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Job);
      else if (xhr.status === 401) { signedOutHandler(); reject(new SignedOut()); }
      else reject(new Error(typeof xhr.response?.detail === "string" ? xhr.response.detail : `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("the upload was interrupted"));
    xhr.send(form);
  });
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`/v1/documents/jobs/${encodeURIComponent(id)}`);
  if (!r.ok) throw await responseError(r);
  return r.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw await responseError(r);
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
): Promise<ChatResponse> {
  const r = await fetch("/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, document_ids: documentIds, stream: true, max_tokens: 1500 }),
    signal,
  });
  if (!r.ok || !r.body) throw await responseError(r);
  let done: ChatResponse | null = null;
  let failure: string | null = null;
  const parser = createSSEParser(({ event, data }) => {
    const payload = JSON.parse(data);
    if (event === "delta") onDelta(payload.text);
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
  if (!done) throw new Error("the connection closed before the answer was complete");
  return done;
}

/** Pages where text may be missing (the warnings that put a document in needs_review). */
export function reviewPages(warnings: Warning[] | undefined): number[] {
  const pages = (warnings ?? []).filter((w) => w.kind === "page_coverage_low" && w.page !== null).map((w) => w.page!);
  return [...new Set(pages)].sort((a, b) => a - b);
}
