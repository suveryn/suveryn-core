/**
 * The gateway API, as used by the UI. All calls are relative (same origin); in development Vite
 * proxies them to the gateway. No other host is ever contacted.
 */
import { createSSEParser } from "./lib/sse";

export type SourceRef = { document_id: string; page: number | null; location: string | null };
export type Citation = { text: string; source: SourceRef | null };
export type ChatResponse = {
  id: string;
  model: string;
  answer: string;
  citations: Citation[];
  finish_reason: string | null;
};
export type WireMessage = { role: "user" | "assistant" | "system"; content: string };

export type JobStatus = "queued" | "processing" | "ready" | "needs_review" | "failed";
export type Job = { id: string; filename: string; status: JobStatus; document_id: string | null; error?: string | null };
export type StoredDocument = {
  id: string;
  filename: string;
  pages: number;
  ocr_pages: number;
  status: "ok" | "needs_review";
  warnings: { page: number | null; kind: string; detail: string }[];
  created_at: string;
  chunks: number;
};
export type Health = {
  status: "ok" | "degraded";
  backend: { reachable: boolean; status: string; model: string | null };
  documents: { status: "ready" | "starting" | "failed" | "unavailable"; detail: string | null };
};

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
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function uploadDocument(file: File): Promise<Job> {
  const form = new FormData();
  form.append("file", file, file.name);
  const r = await fetch("/v1/documents", { method: "POST", body: form });
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`/v1/documents/jobs/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const r = await fetch(`/v1/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw new Error(await errorText(r));
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
  if (!r.ok || !r.body) throw new Error(await errorText(r));
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
