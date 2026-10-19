/** UI-side types for the conversation: turns and attachments. Wire types are in api.ts. */
import type { Calculation, Citation, CitationIssue, JobStatus, Noticed, StreamStatus } from "./api";

/** A file attached to the user's turn. Lives on the user's message, never on the reply. */
export type Attachment = {
  key: string;
  filename: string;
  status: "uploading" | "noticed" | JobStatus;  // noticed: read, but it looks like sūveryn's own output (asks first)
  jobId?: string;
  documentId?: string;
  error?: string;
  progress?: number; // upload progress, 0-1, while status is "uploading"
  reviewPages?: number[]; // with status needs_review: pages where text may be missing
  removed?: boolean; // the document was deleted; its name was taken out (suveryn-tracker#12)
  noticed?: Noticed;  // sūveryn's export mark found in the file (docs/design/sidebar.md §6)
};

export type UserTurn = { id: string; role: "user"; text: string; attachments: Attachment[] };

export type AssistantTurn = {
  id: string;
  role: "assistant";
  text: string;
  citations: Citation[];
  calculations?: Calculation[];
  unverifiedFigures?: string[]; // figures to check: in no source and not calculated by the server
  citationIssues?: CitationIssue[]; // facts a cited source doesn't contain (suveryn-tracker#11)
  instructionLikeSources?: number[]; // passages given to the model whose text addresses an AI (suveryn-tracker#21)
  status: "streaming" | "done" | "stopped" | "error"; // stopped: the person stopped it; the text so far stays, unchecked
  step?: StreamStatus;      // while streaming: the server's latest pipeline step
  grounded: boolean; // the request included documents
  error?: string;
  model?: string;
};

export type Turn = UserTurn | AssistantTurn;

export const isReady = (a: Attachment) => a.status === "ready" || a.status === "needs_review";
export const isPending = (a: Attachment) => ["uploading", "queued", "processing"].includes(a.status);
