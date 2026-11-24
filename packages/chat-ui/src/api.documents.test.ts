/** The documents go through code generated from the gateway's description (suveryn-tracker#248): what each call
 *  sends, and what the gateway's real answers become for the screen. The upload keeps its own sender (only
 *  XMLHttpRequest reports how far an upload is) and the original file is a link: both to the generated address. */
import { afterEach, describe, expect, it, vi } from "vitest";
import documents from "../../api-gateway/tests/documents_answers.json";
import { cancelJob, confirmAsSource, deleteDocument, documentContent, documentConversations, getJob, HttpError, isArchiveUpload, listAllDocuments,
  listDocuments, originalUrl, saveTurnAsDocument, uploadDocument } from "./api";
import type { SavedAnswer } from "./lib/saved";
import { messageText } from "./lib/messages";
import { RateLimited } from "./lib/turns";
import { t } from "./i18n";
import { gatewayAnswers, type KeptAnswer } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const DOC = documents.mine.body.documents[0].id;
const CASE = documents.archive.body.jobs[0].case_id;
const JOB = documents.uploading.body.id;
const refused = async (answer: KeptAnswer, call: () => Promise<unknown>, status: number, code: string) => {
  gatewayAnswers(answer);
  const e = await failure(call());
  expect(e).toBeInstanceOf(HttpError);
  expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText(e.problem, t())]);
  expect(e.message.length).toBeGreaterThan(10);
};

/** The browser's XMLHttpRequest, as far as an upload uses it: it answers with a kept answer. */
function uploadsAnswer(answer: KeptAnswer, headers: Record<string, string> = {}) {
  const sent: { method: string; path: string; parts: [string, string][] }[] = [];
  class Request {
    upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
    status = 0; response: unknown = null; responseType = ""; onload?: () => void; onerror?: () => void; onabort?: () => void;
    private asked = { method: "", path: "" };
    open(method: string, path: string) { this.asked = { method, path }; }
    getResponseHeader(name: string) { return headers[name] ?? null; }
    abort() { this.onabort?.(); }
    send(form: FormData) {
      sent.push({ ...this.asked, parts: [...form.entries()].map(([name, part]) => [name, (part as File).name]) });
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
      this.status = answer.status; this.response = answer.body;
      this.onload?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", Request);
  return sent;
}
const file = (name: string) => new File(["%PDF-1.7"], name, { type: "application/pdf" });

afterEach(() => vi.unstubAllGlobals());

describe("the documents", () => {
  it("lists them: a place's, with the uploads still being read there, and everywhere", async () => {
    const sent = gatewayAnswers(documents.mine, documents.in_case, documents.everywhere);
    const mine = await listDocuments();
    expect(mine.documents.map((d) => [d.id, d.filename, d.pages, d.status, d.origin, d.source, d.provenance, d.warnings])).toEqual([
      [DOC, "akte.pdf", 5, "ok", "uploaded", true, null, []]]);
    expect(mine.jobs.map((j) => [j.status, j.failure?.code])).toEqual([["failed", "document.pages_too_many"]]);
    const [marked] = (await listDocuments(CASE)).documents;
    expect([marked.source, marked.provenance?.noticed?.ref, marked.provenance?.confirmed]).toEqual([false, "A-3f9c2e1b", undefined]);
    expect((await listAllDocuments()).map((d) => d.case_id).sort()).toEqual([CASE, null].sort());
    expect(sent).toEqual([asked("GET", "/v1/documents"), asked("GET", `/v1/documents?case=${CASE}`), asked("GET", "/v1/documents/all")]);
  });

  it("follows an upload while it is read, and cancels one: already read or gone is cancelled all the same", async () => {
    const sent = gatewayAnswers(documents.reading, documents.failed, documents.done, documents.already_read, documents.no_such_document);
    const reading = await getJob(JOB);
    expect([reading.status, reading.progress, reading.pages, reading.document_id, reading.noticed]).toEqual(["processing", { step: "ocr", done: 2, total: 5 }, 5, null, null]);
    expect((await getJob(JOB)).failure).toEqual({ kind: "refused", code: "document.pages_too_many", params: { pages: 900, max: 500 } });
    expect([await cancelJob(JOB), await cancelJob(JOB), await cancelJob(JOB)]).toEqual([undefined, undefined, undefined]);
    expect(sent.map((s) => [s.method, s.path])).toEqual([["GET", `/v1/documents/jobs/${JOB}`], ["GET", `/v1/documents/jobs/${JOB}`],
      ...Array(3).fill(["DELETE", `/v1/documents/jobs/${JOB}`])]);
  });

  it("uses a marked upload as a source, asks which conversations cite a document, and deletes it", async () => {
    const accepted = { status: 202, media_type: null, body: null };
    const sent = gatewayAnswers(documents.used_as_source, documents.citing, documents.done, accepted, documents.no_such_document);
    expect(await confirmAsSource(DOC, CASE)).toBeUndefined();
    expect(await documentConversations(DOC)).toEqual([]);
    expect([await deleteDocument(DOC), await deleteDocument(DOC, "delete", CASE), await deleteDocument(DOC)]).toEqual([undefined, undefined, undefined]);
    expect(sent.map((s) => [s.method, s.path])).toEqual([["POST", `/v1/documents/${DOC}/source?case=${CASE}`], ["GET", `/v1/documents/${DOC}/conversations`],
      ["DELETE", `/v1/documents/${DOC}?conversations=clean`], ["DELETE", `/v1/documents/${DOC}?conversations=delete&case=${CASE}`],
      ["DELETE", `/v1/documents/${DOC}?conversations=clean`]]);
  });

  it("saves an answer the server stored to its case by naming it (#251), and reads back what rebuilds its file", async () => {
    const CONVERSATION = "00000000-0000-4000-8000-0000000000a2";
    const sent = gatewayAnswers(documents.saved_from_turn, documents.content_from_turn);
    const saved = await saveTurnAsDocument(CONVERSATION, 2);
    expect([saved.created, saved.filename]).toEqual([true, "What is the price.docx"]);
    const rebuilt = await documentContent(saved.id, CASE);
    const content = rebuilt.content as SavedAnswer;
    expect([rebuilt.origin, content.question, content.turnId]).toEqual(["answer", "What is the price?", `${CONVERSATION}/2`]);
    expect(sent).toEqual([asked("POST", `/v1/conversations/${CONVERSATION}/turns/2/document`),
      asked("GET", `/v1/documents/${saved.id}/content?case=${CASE}`)]);
  });

  it("an id is one part of the address, whatever is in it; the original file's address too", async () => {
    const sent = gatewayAnswers(documents.no_such_document, documents.no_such_document, documents.no_such_document);
    await failure(getJob("a/b?c"));
    await failure(documentContent("../x", "c&d"));
    await deleteDocument("a b", "clean", "c/1");
    expect(sent.map((s) => s.path)).toEqual(["/v1/documents/jobs/a%2Fb%3Fc", "/v1/documents/..%2Fx/content?case=c%26d", "/v1/documents/a%20b?conversations=clean&case=c%2F1"]);
    expect([originalUrl("a/b"), originalUrl(DOC, CASE, 3), originalUrl(DOC, null, null)]).toEqual([
      "/v1/documents/a%2Fb/original", `/v1/documents/${DOC}/original?case=${CASE}#page=3`, `/v1/documents/${DOC}/original`]);
  });

  it("each refusal is thrown with its status, its code and the code's words", async () => {
    await refused(documents.no_such_document, () => getJob(JOB), 404, "request.not_found");
    await refused(documents.no_such_document, () => documentContent(DOC), 404, "request.not_found");
    await refused(documents.no_such_document, () => confirmAsSource(DOC), 404, "request.not_found");
    await refused(documents.disk_full, () => deleteDocument(DOC), 507, "upload.disk_full");
  });
});

describe("an upload", () => {
  it("goes to the generated address as the generated body, says how far it is, and answers a job", async () => {
    const sent = uploadsAnswer(documents.uploading);
    const progress: number[] = [];
    const job = await uploadDocument(file("akte.pdf"), (fraction) => progress.push(fraction), CASE);
    expect(isArchiveUpload(job)).toBe(false);
    expect(job).toMatchObject({ id: JOB, filename: "akte.pdf", status: "queued", document_id: null, failure: null });
    expect([sent, progress]).toEqual([[{ method: "POST", path: `/v1/documents?case=${CASE}`, parts: [["file", "akte.pdf"]] }], [0.5]]);
  });

  it("of a .zip answers a job per document inside, and what was left out", async () => {
    const sent = uploadsAnswer(documents.archive);
    const archive = await uploadDocument(file("stukken.zip"));
    expect(isArchiveUpload(archive) && [archive.archive, archive.jobs.map((j) => j.filename), archive.skipped.map((s) => [s.name, s.failure.code])]).toEqual([
      "stukken.zip", ["akte.pdf", "notes.docx"], [["photo.jpg", "upload.unsupported"]]]);
    expect(sent[0].path).toBe("/v1/documents");
  });

  it("that is refused says why in the code's words; a full queue or too many at once is waited for", async () => {
    for (const [answer, code] of [[documents.too_large, "upload.too_large"], [documents.not_read, "upload.unsupported"], [documents.disk_full, "upload.disk_full"]] as const) {
      uploadsAnswer(answer);
      const e = await failure(uploadDocument(file("akte.pdf")));
      expect([e instanceof RateLimited, e.message]).toEqual([false, messageText({ kind: answer.body.kind as "refused", code, params: answer.body.params }, t())]);
    }
    uploadsAnswer(documents.too_many_waiting);
    const waiting = await failure(uploadDocument(file("akte.pdf")));
    expect([waiting instanceof RateLimited, waiting.seconds]).toEqual([true, 10]);
  });
});
