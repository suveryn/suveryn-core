import { describe, expect, it } from "vitest";
import { inTurn, MAX_TURNS, pause, RateLimited } from "./turns";

describe("an upload refused by the rate limit", () => {
  it("is sent again after the wait the gateway names, and other errors are not", async () => {
    const waits: number[] = [];
    let calls = 0;
    const send = async () => {
      calls += 1;
      if (calls < 3) throw new RateLimited("too many requests", 32);
      return "job-1";
    };
    const said: number[] = [];
    expect(await inTurn(send, (s) => said.push(s), undefined, async (ms) => { waits.push(ms); })).toBe("job-1");
    expect(waits).toEqual([32_000, 32_000]);
    expect(said).toEqual([32, 32]);
    await expect(inTurn(async () => { throw new Error("file not supported"); }, () => {}, undefined, async () => {}))
      .rejects.toThrow("file not supported");
  });

  it("gives up after a number of turns, and stops waiting when the card is removed", async () => {
    let calls = 0;
    await expect(inTurn(async () => { calls += 1; throw new RateLimited("busy", 1); }, () => {}, undefined, async () => {}))
      .rejects.toBeInstanceOf(RateLimited);
    expect(calls).toBe(MAX_TURNS);
    const abort = new AbortController();
    const waiting = pause(60_000, abort.signal);
    abort.abort();
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
  });
});
