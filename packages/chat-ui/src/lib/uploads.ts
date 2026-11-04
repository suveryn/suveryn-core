/**
 * Uploads still being read: asking the server how each is doing, and what its card shows.
 *
 * The server forgets a finished job an hour after it ends (rag/service.py, ``JOB_RETENTION_S``), and a
 * restart forgets them all. A restart also ends every session, so the page signs out and its cards go
 * with it; the case that remains is a page that stopped asking for over an hour (a laptop asleep, a tab
 * the browser froze) and wakes to a job the server no longer knows. It answered 404, and the chat took
 * that for a passing error: the card said "reading" for ever, asked again every 1.5 s, and a question
 * waited for it (audit of 4 November 2026, finding 2). Now such a job is ``lost``: the card says the page
 * lost track of the upload and to add it again if it isn't in the documents, which are refreshed.
 */
import { getJob, HttpError, type Job } from "../api";
import type { Messages } from "../i18n";
import type { Attachment } from "../types";
import { cardNote, checkPages, readingNotes, toCheck } from "./readingNotes";

/** The reader's code for an upload the server no longer knows (``failureText``). */
export const LOST_TRACK = "lost";

/** The server's answer for a job: the job, or ``lost`` when it no longer knows it (404). */
export type Checked = Job | "lost";

/** Whether an attachment is still with the server: waiting, or being read. */
export const stillReading = (a: Attachment): boolean => !!a.jobId && (a.status === "queued" || a.status === "processing");

/** One job's state, or ``lost`` (404); throws on anything else, which is worth asking again. */
export async function checkJob(id: string, get: (id: string) => Promise<Job> = getJob): Promise<Checked> {
  try {
    return await get(id);
  } catch (e) {
    if (e instanceof HttpError && e.status === 404) return "lost";
    throw e;
  }
}

/** Every job's state, by id. A job whose check failed for another reason (the network, a 503 while the
 *  gateway starts) is left out: it is asked again next round. */
export async function checkJobs(ids: string[], get: (id: string) => Promise<Job> = getJob): Promise<Map<string, Checked>> {
  const out = new Map<string, Checked>();
  await Promise.all(ids.map(async (id) => {
    try { out.set(id, await checkJob(id, get)); } catch { /* asked again next round */ }
  }));
  return out;
}

/** The card for an attachment, from its job. */
export function attachmentFromJob(m: Messages, a: Attachment, j: Job): Attachment {
  const noticed = j.noticed && (j.status === "ready" || j.status === "needs_review") ? j.noticed : undefined;
  // What the reading noticed puts it on "To check" too, and says so once on the card (suveryn-tracker#26)
  const status = j.status === "ready" && toCheck(readingNotes(j.warnings)) ? "needs_review" : j.status;
  return { ...a, status: noticed ? "noticed" : status, noticed, documentId: j.document_id ?? undefined,
           error: j.error ?? undefined, reviewPages: checkPages(j.warnings), pages: j.pages ?? undefined,
           note: cardNote(m, j.warnings) ?? undefined,
           reading: j.status === "processing" ? j.progress ?? null : null, errorCode: j.error_code ?? undefined,
           errorDetail: j.error_detail ?? undefined };
}

/** The card after a round of checks: unchanged if its job wasn't checked, failed and interrupted if lost. */
export function afterCheck(m: Messages, a: Attachment, checked: Map<string, Checked>): Attachment {
  const c = a.jobId ? checked.get(a.jobId) : undefined;
  if (c === undefined) return a;
  if (c === "lost") return { ...a, status: "failed", errorCode: LOST_TRACK, reading: null };
  return attachmentFromJob(m, a, c);
}
