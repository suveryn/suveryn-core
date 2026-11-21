/** The clock's calls go through code generated from the gateway's description (suveryn-tracker#236): what they send,
 *  and what each of the gateway's real answers becomes for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import answers from "../../api-gateway/tests/clock_answers.json";
import { applianceClockAnswer, HttpError, onSignedOut, setApplianceClock } from "./api";
import { measureClock, reportClock, sendClock } from "./lib/clock";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const measured = { offset_ms: -95_000, rtt_ms: 40 };

afterEach(() => { vi.unstubAllGlobals(); onSignedOut(() => {}); });

describe("an administrator sets the appliance's clock", () => {
  it("asks with the measurement, then for the answer by its id", async () => {
    const sent = gatewayAnswers(answers.asked, answers.pending, answers.set);
    const asked = await setApplianceClock(measured);
    expect(asked).toEqual(answers.asked.body);
    expect(await applianceClockAnswer(asked.id)).toMatchObject({ pending: true });
    expect(await applianceClockAnswer(asked.id)).toEqual({ id: asked.id, pending: false, ok: true, failure: null, moved_ms: 95_000 });
    expect(sent).toEqual([
      { method: "POST", path: "/v1/admin/clock", body: measured, cache: "default" },
      { method: "GET", path: `/v1/admin/clock/${asked.id}`, body: null, cache: "default" },
      { method: "GET", path: `/v1/admin/clock/${asked.id}`, body: null, cache: "default" },
    ]);
  });

  it("an id is one part of the address, whatever is in it", async () => {
    const sent = gatewayAnswers(answers.no_such_request);
    await failure(applianceClockAnswer("a/b?c"));
    expect(sent[0].path).toBe("/v1/admin/clock/a%2Fb%3Fc");
  });

  it("the appliance's own refusal travels inside the answer, as a message the screen words", async () => {
    gatewayAnswers(answers.not_set);
    const answer = await applianceClockAnswer("0123456789abcdef");
    expect(answer.ok).toBe(false);
    expect(messageText(answer.failure!, t())).toBe(t().messages["clock.synced"]);
  });

  it.each([
    ["synced", 409, "clock.synced"], ["busy", 409, "clock.busy"], ["too_slow", 422, "clock.measurement_too_slow"],
    ["unavailable", 503, "clock.unavailable"], ["not_an_administrator", 403, "request.forbidden"], ["invalid", 422, "request.invalid"],
  ] as const)("a refusal (%s) is thrown with its status, its code and the code's words", async (name, status, code) => {
    gatewayAnswers(answers[name]);
    const e = await failure(setApplianceClock(measured));
    expect(e).toBeInstanceOf(HttpError);
    expect([e.status, e.problem.code, e.problem.kind]).toEqual([status, code, answers[name].body.kind]);
    expect(e.message).toBe(messageText({ code }, t()));
    expect(e.message.length).toBeGreaterThan(10);
  });

  it("what nobody planned for shows its reference", async () => {
    gatewayAnswers(answers.unplanned);
    const e = await failure(applianceClockAnswer("0123456789abcdef"));
    expect([e.status, e.problem.code, e.problem.params]).toEqual([500, "system.internal", { ref: "7F3K-92QD" }]);
    expect(e.message).toContain("7F3K-92QD");
  });

  it("a signed-out session shows the sign-in screen", async () => {
    let shown = 0;
    onSignedOut(() => { shown++; });
    gatewayAnswers(answers.signed_out);
    const e = await failure(setApplianceClock(measured));
    expect(shown).toBe(1);
    expect(e).not.toBeInstanceOf(HttpError);
    expect(e.message).toBe(t().messages["auth.signed_out"]);
  });

  it("an answer that isn't the gateway's (a proxy's page, an empty one) gets the status's general words", async () => {
    gatewayAnswers(new Response("<html>Bad gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } }),
      new Response(null, { status: 503 }), new Response("{not json", { status: 500, headers: { "Content-Type": "application/json" } }));
    for (const [status, kind] of [[502, "unavailable"], [503, "unavailable"], [500, "internal"]] as const) {
      const e = await failure(setApplianceClock(measured));
      expect([e.status, e.problem.kind]).toEqual([status, kind]);
      expect(e.message.length).toBeGreaterThan(10);
    }
  });

  it("an answer that says it went well but isn't the gateway's is a failure, never the answer", async () => {
    const page = () => new Response("<html>Sign in to the hotel's network</html>", { status: 200, headers: { "Content-Type": "text/html" } });
    const cut = () => new Response('{"id": "0123', { status: 200, headers: { "Content-Type": "application/json" } });
    const bare = () => new Response("ok", { status: 200 });
    const empty = () => new Response("", { status: 200, headers: { "Content-Type": "application/json" } });
    for (const answer of [page, cut, bare, empty]) {
      gatewayAnswers(answer());
      const e = await failure(applianceClockAnswer("0123456789abcdef"));
      expect(e).toBeInstanceOf(HttpError);
      expect([e.status, e.problem.kind, e.message]).toEqual([200, "unavailable", messageText(e.problem, t())]);
      gatewayAnswers(answer());
      expect(await failure(measureClock())).toBeInstanceOf(HttpError);
      gatewayAnswers(answer());
      await reportClock(); // and the hourly report stays quiet
    }
  });

  it("the answer's type is read whatever its letters' case", async () => {
    gatewayAnswers(new Response(JSON.stringify(answers.set.body), { status: 200, headers: { "Content-Type": "Application/JSON; charset=utf-8" } }));
    expect(await applianceClockAnswer("0123456789abcdef")).toEqual(answers.set.body);
  });

  it("no network is the browser's own failure, as before", async () => {
    gatewayAnswers(new TypeError("Failed to fetch"));
    const e = await failure(setApplianceClock(measured));
    expect(e).toBeInstanceOf(TypeError);
    expect(e.message).toBe("Failed to fetch");
  });
});

describe("a signed-in browser measures and reports", () => {
  it("measures three times, never from the browser's cache, and keeps the quickest", async () => {
    const now = { ...answers.now, body: { now_ms: Date.now() + 5000 } };
    const sent = gatewayAnswers(now, now, now);
    const m = await measureClock();
    expect(sent).toEqual(Array(3).fill({ method: "GET", path: "/v1/clock", body: null, cache: "no-store" }));
    expect(m!.rtt_ms).toBeLessThan(1000);
    expect(Math.abs(m!.offset_ms - 5000)).toBeLessThan(1000);
  });

  it("reads the clock out of the gateway's own answer", async () => {
    gatewayAnswers(answers.now, answers.now, answers.now);
    const before = Date.now();
    expect((await measureClock())!.offset_ms).toBeLessThanOrEqual(answers.now.body.now_ms - before);
  });

  it("measures nothing when the gateway refuses or is down, and fails as the browser does without a network", async () => {
    for (const refusal of [answers.signed_out, answers.unavailable, new Response("<html>", { status: 502 })]) {
      gatewayAnswers(refusal);
      expect(await measureClock()).toBeNull();
    }
    gatewayAnswers(new TypeError("Failed to fetch"));
    expect(await failure(measureClock())).toBeInstanceOf(TypeError);
  });

  it("a signed-out session met while measuring doesn't show the sign-in screen: the clock is not the page's business", async () => {
    let shown = 0;
    onSignedOut(() => { shown++; });
    gatewayAnswers(answers.signed_out);
    await reportClock();
    expect(shown).toBe(0);
  });

  it("reports the measurement, and a refusal or no network changes nothing for the page", async () => {
    let sent = gatewayAnswers(answers.reported);
    await sendClock({ offset_ms: 2500, rtt_ms: 30 });
    expect(sent).toEqual([{ method: "POST", path: "/v1/clock", body: { offset_ms: 2500, rtt_ms: 30 }, cache: "default" }]);
    gatewayAnswers(answers.invalid);
    await sendClock({ offset_ms: 2500, rtt_ms: 30 });
    const now = { ...answers.now, body: { now_ms: Date.now() } };
    sent = gatewayAnswers(now, now, now, new TypeError("Failed to fetch"));
    await reportClock();
    expect(sent.map((s) => s.method)).toEqual(["GET", "GET", "GET", "POST"]);
    gatewayAnswers(new TypeError("Failed to fetch"));
    await reportClock();
  });
});
