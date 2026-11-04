import { describe, expect, it } from "vitest";
import { HttpError, type Job } from "../api";
import en from "../i18n/en";
import fr from "../i18n/fr";
import nl from "../i18n/nl";
import type { Attachment } from "../types";
import { failureText } from "./review";
import { afterCheck, checkJob, checkJobs, LOST_TRACK, stillReading } from "./uploads";

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
