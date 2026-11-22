/** Health and Administration › Status go through code generated from the gateway's description (suveryn-tracker#238). */
import { afterEach, describe, expect, it, vi } from "vitest";
import status from "../../api-gateway/tests/status_answers.json";
import { getAdminStatus, getHealth, HttpError, onSignedOut } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);

afterEach(() => { vi.unstubAllGlobals(); onSignedOut(() => {}); });

describe("health", () => {
  it("is the same body whether the model server is ready, loading or away", async () => {
    const sent = gatewayAnswers(status.ready, status.loading, status.unreachable);
    expect(await getHealth()).toEqual(status.ready.body);
    expect((await getHealth())?.backend).toMatchObject({ reachable: true, status: "loading" });
    expect(await getHealth()).toMatchObject({ status: "degraded", backend: { reachable: false, status: "unreachable" } });
    expect(sent).toEqual(Array(3).fill({ method: "GET", path: "/health", body: null, cache: "default" }));
  });

  it("is nothing when the gateway isn't reached, or answers something that isn't its health", async () => {
    let shown = 0;
    onSignedOut(() => { shown++; });
    const unplanned = { status: 500, media_type: "application/problem+json", body: { type: "urn:suveryn:problem:system.internal", title: "t", status: 500,
      detail: "d", kind: "internal", code: "system.internal", params: { ref: "7F3K-92QD" } } };
    for (const answer of [new TypeError("Failed to fetch"), unplanned, new Response("<html>Bad gateway</html>", { status: 502 }),
      new Response("<html>Sign in to the hotel's network</html>", { status: 200, headers: { "Content-Type": "text/html" } }),
      new Response('{"status": "o', { status: 200, headers: { "Content-Type": "application/json" } }), new Response(null, { status: 401 })]) {
      gatewayAnswers(answer);
      expect(await getHealth()).toBeNull();
    }
    expect(shown).toBe(0); // health is asked before anyone is signed in
  });
});

describe("Administration › Status", () => {
  it("reads the six checks", async () => {
    const sent = gatewayAnswers(status.checks);
    const answer = await getAdminStatus();
    expect(answer.checks.map((c) => c.id)).toEqual(["answering", "reading", "signin", "data", "disk", "clock"]);
    expect(answer).toEqual(status.checks.body);
    expect(sent).toEqual([{ method: "GET", path: "/v1/admin/status", body: null, cache: "default" }]);
  });

  it("someone who isn't an administrator is refused with the code's words", async () => {
    gatewayAnswers(status.not_an_administrator);
    const e = await failure(getAdminStatus());
    expect(e).toBeInstanceOf(HttpError);
    expect([e.status, e.problem.code, e.message]).toEqual([403, "request.forbidden", messageText({ code: "request.forbidden" }, t())]);
  });
});
