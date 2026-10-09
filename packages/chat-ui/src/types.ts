import type { Citation, JobStatus } from "./api";

/** A file attached to the user's turn. Lives on the user's message, never on the reply. */
export type Attachment = {
  key: string;
  filename: string;
  status: "uploading" | JobStatus;
  jobId?: string;
  documentId?: string;
  error?: string;
};

export type UserTurn = { id: string; role: "user"; text: string; attachments: Attachment[] };

export type AssistantTurn = {
  id: string;
  role: "assistant";
  text: string;
  citations: Citation[];
  status: "streaming" | "done" | "error";
  grounded: boolean; // the request included documents
  error?: string;
  model?: string;
};

export type Turn = UserTurn | AssistantTurn;

export const isReady = (a: Attachment) => a.status === "ready" || a.status === "needs_review";
export const isPending = (a: Attachment) => ["uploading", "queued", "processing"].includes(a.status);
