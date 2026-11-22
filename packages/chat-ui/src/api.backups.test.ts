/** Administration › Backups goes through code generated from the gateway's description (suveryn-tracker#240). */
import { afterEach, describe, expect, it, vi } from "vitest";
import backups from "../../api-gateway/tests/backups_answers.json";
import { askBackupService, getBackups, HttpError, testRecoveryKey } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const KEY_FILE = `# Sūveryn backup recovery key\n${"AGE-SECRET-KEY-1" + "Q".repeat(58)}\n`;

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("what the backup service recorded", () => {
  it("is read as the gateway gives it, also when there is no backup service", async () => {
    const sent = gatewayAnswers(backups.never_ran, backups.as_recorded);
    expect(await getBackups()).toMatchObject({ available: false, configured: false, last_success: null, settings: null });
    const status = await getBackups();
    expect(status).toEqual(backups.as_recorded.body);
    expect(messageText(status.last_error!.failure, t())).toBe(t().messages["backup.target_unreachable"]);
    expect([status.key_test!.failure!.code, status.settings!.retention_days, status.settings!.has_password]).toEqual(["backup.key_mismatch", 90, true]);
    expect(sent).toEqual([asked("GET", "/v1/admin/backups"), asked("GET", "/v1/admin/backups")]);
  });
});

describe("testing the recovery key", () => {
  it("sends the key file as it is, and is done when the gateway has accepted it", async () => {
    const sent = gatewayAnswers(backups.key_accepted);
    expect(await testRecoveryKey(KEY_FILE)).toBeUndefined();
    expect(sent).toEqual([asked("POST", "/v1/admin/backups/key-test", KEY_FILE)]);
  });

  it.each([
    ["a file that isn't a key", backups.not_a_key, 415, "backup.not_a_key"],
    ["a test already running", backups.key_test_running, 409, "backup.busy"],
    ["no backup service", backups.no_backup_service, 503, "backup.unavailable"],
  ] as const)("%s is thrown with its status, its code and the code's words", async (_, answer, status, code) => {
    gatewayAnswers(answer);
    const e = await failure(testRecoveryKey(KEY_FILE));
    expect(e).toBeInstanceOf(HttpError);
    expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText({ code }, t())]);
  });

  it("an accepted answer that isn't the gateway's is a failure: a page, or done where it should be accepted", async () => {
    for (const answer of [new Response("<html>Sign in to the hotel's network</html>", { status: 202, headers: { "Content-Type": "text/html" } }),
      new Response(null, { status: 200 }), new Response(JSON.stringify({ id: "x" }), { status: 202, headers: { "Content-Type": "application/json" } })]) {
      gatewayAnswers(answer);
      expect(await failure(testRecoveryKey(KEY_FILE))).toBeInstanceOf(HttpError);
    }
  });
});

describe("asking the backup service", () => {
  it("asks, then asks for the answer by its id every second until it has answered", async () => {
    vi.useFakeTimers();
    const sent = gatewayAnswers(backups.asked, backups.pending, backups.disks);
    const answer = askBackupService({ kind: "disks" });
    await vi.advanceTimersByTimeAsync(2000);
    expect((await answer).disks).toEqual([{ id: "usb-Extreme_SER1", name: "Extreme", size_bytes: 10 ** 12 }]);
    const id = backups.asked.body.id;
    expect(sent).toEqual([asked("POST", "/v1/admin/backups/requests", { kind: "disks" }),
      asked("GET", `/v1/admin/backups/requests/${id}`), asked("GET", `/v1/admin/backups/requests/${id}`)]);
  });

  it("hands on why not: for a field of the form, or for the request", async () => {
    vi.useFakeTimers();
    for (const [answer, read] of [
      [backups.a_field_refused, (a: Awaited<ReturnType<typeof askBackupService>>) => a.fields!.address.code],
      [backups.failed, (a: Awaited<ReturnType<typeof askBackupService>>) => a.failure!.code],
    ] as const) {
      gatewayAnswers(backups.asked, answer);
      const asking = askBackupService({ kind: "run" });
      await vi.advanceTimersByTimeAsync(1000);
      expect([(await asking).ok, read(await asking)]).toEqual([false, answer === backups.failed ? "backup.target_unreachable" : "backup.share_address_invalid"]);
    }
    gatewayAnswers(backups.asked, backups.saved);
    const saving = askBackupService({ kind: "settings", target: "usb", retention_days: 30, hour: 2 });
    await vi.advanceTimersByTimeAsync(1000);
    expect(await saving).toMatchObject({ ok: true, key_changed: true });
  });

  it.each([
    ["the service still busy", backups.busy, 409, "backup.busy"],
    ["settings with a part missing", backups.settings_incomplete, 422, "request.invalid"],
    ["someone who isn't an administrator", backups.not_an_administrator, 403, "request.forbidden"],
  ] as const)("%s is thrown with its status, its code and the code's words", async (_, answer, status, code) => {
    gatewayAnswers(answer);
    const e = await failure(askBackupService({ kind: "run" }));
    expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText({ code }, t())]);
  });

  it("an accepted answer with nothing in it is not the gateway's: asking is answered with an id", async () => {
    gatewayAnswers(new Response(null, { status: 202 }));
    const e = await failure(askBackupService({ kind: "run" }));
    expect(e).toBeInstanceOf(HttpError);
    expect(e.message).toBe(messageText(e.problem, t()));
  });

  it("gives up in words when the service doesn't answer in time", async () => {
    vi.useFakeTimers();
    gatewayAnswers(backups.asked, backups.pending, backups.pending);
    const asking = failure(askBackupService({ kind: "run" }, 2));
    await vi.advanceTimersByTimeAsync(2000);
    expect((await asking).message).toBe(messageText({ kind: "unavailable", code: "backup.unavailable" }, t()));
  });
});
