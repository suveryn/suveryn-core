import { describe, expect, it } from "vitest";
import { HttpError, type Job, type StoredDocument } from "../api";
import en from "../i18n/en";
import fr from "../i18n/fr";
import nl from "../i18n/nl";
import type { Attachment, Turn } from "../types";
import { failureText } from "./review";
import { afterCheck, archiveCards, cardForStored, checkJob, checkJobs, documentsChanged, LOST_TRACK, readToChoose, removal, stillReading,
         uploadsToCheck, usedAsSource } from "./uploads";

const job = (id: string, status: Job["status"], extra: Partial<Job> = {}): Job =>
  ({ id, filename: `${id}.pdf`, status, document_id: status === "ready" ? `doc-${id}` : null, error: null, pages: 3,
     warnings: [], ...extra }) as unknown as Job;
const card = (jobId: string, status: Attachment["status"] = "queued"): Attachment => ({ key: jobId, filename: `${jobId}.pdf`, status, jobId });

describe("an upload the server no longer knows (audit of 4 November 2026, finding 2)", () => {
  it("a job the server no longer knows is lost, not asked about for ever", async () => {
    const gone = async (): Promise<Job> => { throw new HttpError("Not found", 404); };
    expect(await checkJob("a", gone)).toBe("lost");
  });

  it("any other failure is asked again next round, not taken for lost", async () => {
    const starting = async (): Promise<Job> => { throw new HttpError("Starting", 503); };
    await expect(checkJob("a", starting)).rejects.toThrow("Starting");
    const offline = async (): Promise<Job> => { throw new TypeError("Failed to fetch"); };
    expect((await checkJobs(["a"], offline)).size).toBe(0);
  });

  it("a round of checks: read, still waiting, lost, and one that couldn't be asked", async () => {
    const answers: Record<string, () => Promise<Job>> = {
      read: async () => job("read", "ready"),
      waiting: async () => job("waiting", "queued"),
      lost: async () => { throw new HttpError("Not found", 404); },
      flaky: async () => { throw new TypeError("Failed to fetch"); },
    };
    const checked = await checkJobs(Object.keys(answers), (id) => answers[id]());
    expect(checked.get("read")).toMatchObject({ status: "ready" });
    expect(checked.get("waiting")).toMatchObject({ status: "queued" });
    expect(checked.get("lost")).toBe("lost");
    expect(checked.has("flaky")).toBe(false);

    const lost = afterCheck(en, card("lost"), checked);
    expect(lost).toMatchObject({ status: "failed", errorCode: LOST_TRACK });
    expect(stillReading(lost)).toBe(false); // so the chat stops asking, and a question no longer waits for it
    expect(afterCheck(en, card("read"), checked)).toMatchObject({ status: "ready", documentId: "doc-read" });
    expect(stillReading(afterCheck(en, card("waiting"), checked))).toBe(true);
    const flaky = card("flaky", "processing");
    expect(afterCheck(en, flaky, checked)).toBe(flaky); // unchanged: asked again next round
  });

  it("the card says the page lost track of it and to add it again if it isn't there, in every language", () => {
    for (const m of [en, nl, fr]) {
      const text = failureText(m, LOST_TRACK);
      expect(text).toBe(m.failLostTrack);
      expect(text.length).toBeGreaterThan(20);
    }
    expect(failureText(en, LOST_TRACK)).toMatch(/lost track.*add it again/);
  });
});

describe("the composer's cards (App.tsx, now lib/uploads.ts)", () => {
  const read = (key: string, extra: Partial<Attachment> = {}): Attachment =>
    ({ key, filename: `${key}.pdf`, status: "ready", documentId: `doc-${key}`, ...extra });

  it("asks about what is still with the server, in the composer and in the conversation", () => {
    const turns: Turn[] = [{ id: "u", role: "user", text: "?", attachments: [card("earlier", "processing"), read("done")] }];
    const pending = [card("new"), card("sending", "uploading"), read("ready")];
    expect(uploadsToCheck(pending, turns).map((a) => a.key)).toEqual(["new", "earlier"]);
  });

  it("reads the documents again once a job finished or was lost, not while all are still waiting", () => {
    expect(documentsChanged(new Map([["a", job("a", "queued")], ["b", job("b", "processing")]]))).toBe(false);
    expect(documentsChanged(new Map([["a", job("a", "queued")], ["b", job("b", "ready")]]))).toBe(true);
    expect(documentsChanged(new Map([["a", job("a", "failed")]]))).toBe(true);
    expect(documentsChanged(new Map([["a", "lost" as const]]))).toBe(true);
    expect(documentsChanged(new Map())).toBe(false);
  });

  it("turns an archive into a card per document, and one per file left out with the reason", () => {
    let n = 0;
    const cards = archiveCards(en, { archive: "dossier.zip", jobs: [job("a", "queued"), job("b", "queued")],
                                     skipped: [{ name: "foto.heic", reason: "not a document sūveryn reads" }] }, () => `k${++n}`);
    expect(cards.map((c) => [c.key, c.filename, c.status])).toEqual([["k1", "a.pdf", "queued"], ["k2", "b.pdf", "queued"], ["k3", "foto.heic", "failed"]]);
    expect(cards[2]).toMatchObject({ notAdded: true, error: en.archiveSkipped({ archive: "dossier.zip", reason: "not a document sūveryn reads" }) });
  });

  it("attaches a stored document as read, on 'To check' when it needs review", () => {
    const doc = { id: "d1", filename: "akte.pdf", status: "ok", warnings: [], pages: 12 } as unknown as StoredDocument;
    expect(cardForStored(doc, "k")).toMatchObject({ key: "k", filename: "akte.pdf", documentId: "d1", status: "ready", pages: 12 });
    expect(cardForStored({ ...doc, status: "needs_review" }, "k").status).toBe("needs_review");
    expect(cardForStored({ ...doc, pages: 0 }, "k").pages).toBeUndefined();
  });

  it("the ×: stops an upload on its way, cancels a job waiting or being read, and takes a read one out of the question", () => {
    expect(removal(card("a", "uploading"))).toEqual({ stop: "upload", unchoose: null });
    expect(removal(card("a", "queued"))).toEqual({ stop: "job", unchoose: null });
    expect(removal(card("a", "processing"))).toEqual({ stop: "job", unchoose: null });
    expect(removal(read("a"))).toEqual({ stop: null, unchoose: "doc-a" });
    expect(removal({ ...card("a", "failed"), jobId: undefined })).toEqual({ stop: null, unchoose: null });
  });

  it("an upload used as a source anyway is ready, or on 'To check' when its reading noticed something", () => {
    const noticed = read("a", { status: "noticed", noticed: { ref: "r", kind: "answer", line: "…" } });
    expect(usedAsSource(noticed)).toMatchObject({ status: "ready", noticed: undefined });
    expect(usedAsSource({ ...noticed, reviewPages: [3] }).status).toBe("needs_review");
    expect(usedAsSource({ ...noticed, note: "Text addressed to an AI" }).status).toBe("needs_review");
  });

  it("in a case, chooses what is read and not chosen yet", () => {
    const pending = [read("a"), read("b", { status: "needs_review" }), card("c", "processing"), read("d")];
    expect(readToChoose(pending, [{ documentId: "doc-d", filename: "d.pdf" }])).toEqual([
      { id: "doc-a", filename: "a.pdf" }, { id: "doc-b", filename: "b.pdf" }]);
  });
});
