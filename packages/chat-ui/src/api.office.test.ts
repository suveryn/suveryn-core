/** Usage, the models and the office's settings go through code generated from the gateway's description
 *  (suveryn-tracker#237): what each call sends, and what the gateway's real answers become for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import models from "../../api-gateway/tests/models_answers.json";
import settings from "../../api-gateway/tests/settings_answers.json";
import usage from "../../api-gateway/tests/usage_answers.json";
import { getCaseSettings, getMyUsage, getOfficeUsage, getRates, HttpError, listModels, onSignedOut, previewCaseSettings, setCaseSettings,
  setRates } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const from = new Date("2026-11-02T00:00:00Z"), to = new Date("2026-11-09T00:00:00Z");

afterEach(() => { vi.unstubAllGlobals(); onSignedOut(() => {}); });

describe("usage", () => {
  it("asks for a range, and without an end leaves the end to the server's clock", async () => {
    const sent = gatewayAnswers(usage.mine, usage.mine, usage.office);
    expect(await getMyUsage(from, to)).toEqual(usage.mine.body);
    await getMyUsage(from);
    const office = await getOfficeUsage(from, to);
    expect([office.per_user[0].user_id, office.rates.currency, office.cost]).toEqual(["user-b", "USD", "0.01"]);
    expect(sent).toEqual([
      asked("GET", "/v1/usage?start=2026-11-02T00%3A00%3A00.000Z&end=2026-11-09T00%3A00%3A00.000Z"),
      asked("GET", "/v1/usage?start=2026-11-02T00%3A00%3A00.000Z"),
      asked("GET", "/v1/admin/usage?start=2026-11-02T00%3A00%3A00.000Z&end=2026-11-09T00%3A00%3A00.000Z"),
    ]);
  });

  it("reads the rates and saves only the three an administrator sets", async () => {
    const sent = gatewayAnswers(usage.rates, usage.rates_saved);
    expect((await getRates()).input_per_million).toBe("3");
    const change = { input_per_million: "2.5", output_per_million: "10", currency: "EUR" };
    expect(await setRates(change)).toMatchObject({ ...change, updated_by: "Test Notaris" });
    expect(sent).toEqual([asked("GET", "/v1/admin/usage/rates"), asked("PUT", "/v1/admin/usage/rates", change)]);
  });

  it.each([
    ["a range the gateway refuses", () => getMyUsage(to, from), usage.range_refused, 422, "request.invalid"],
    ["someone who isn't an administrator", () => getOfficeUsage(from), usage.not_an_administrator, 403, "request.forbidden"],
    ["rates it refuses", () => setRates({ input_per_million: "-1", output_per_million: "1", currency: "USD" }), usage.rates_refused, 422, "request.invalid"],
  ] as const)("%s is thrown with its status, its code and the code's words", async (_, call, answer, status, code) => {
    gatewayAnswers(answer);
    const e = await failure(call());
    expect(e).toBeInstanceOf(HttpError);
    expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText({ code }, t())]);
  });
});

describe("the models", () => {
  it("lists what is installed, and says in words when the model server is away", async () => {
    const sent = gatewayAnswers(models.installed, models.unavailable);
    expect(await listModels()).toEqual(models.installed.body);
    const e = await failure(listModels());
    expect([e.status, e.problem.code, e.message]).toEqual([503, "model.unavailable", messageText({ code: "model.unavailable" }, t())]);
    expect(sent).toEqual([asked("GET", "/v1/models"), asked("GET", "/v1/models")]);
  });

  it("a session that ended shows the sign-in screen", async () => {
    let shown = 0;
    onSignedOut(() => { shown++; });
    gatewayAnswers(models.signed_out);
    expect(await failure(listModels())).not.toBeInstanceOf(HttpError);
    expect(shown).toBe(1);
  });
});

describe("the office's settings", () => {
  it("reads them, asks what a change would do with only what was chosen, and saves the change", async () => {
    const sent = gatewayAnswers(settings.as_provisioned, settings.preview, settings.preview, settings.saved);
    expect(await getCaseSettings()).toEqual(settings.as_provisioned.body);
    expect(await previewCaseSettings({ default_access: "office", apply_to: "all" })).toEqual({ cases_opened: 1, cases_closed: 0, conversations_deleted: 0 });
    await previewCaseSettings({ conversations_keep: "1y", default_access: undefined });
    const change = { default_access: "office", keep: "1y", office_name: "Notariaat Test" } as const;
    expect(await setCaseSettings(change)).toMatchObject(change);
    expect(sent).toEqual([
      asked("GET", "/v1/admin/cases/settings"),
      asked("GET", "/v1/admin/cases/settings/preview?default_access=office&apply_to=all"),
      asked("GET", "/v1/admin/cases/settings/preview?conversations_keep=1y"),
      asked("PUT", "/v1/admin/cases/settings", change),
    ]);
  });

  it.each([
    ["nothing to change", settings.nothing_to_change, 422, "request.invalid"],
    ["someone who isn't an administrator", settings.not_an_administrator, 403, "request.forbidden"],
  ] as const)("%s is thrown with its status, its code and the code's words", async (_, answer, status, code) => {
    gatewayAnswers(answer);
    const e = await failure(setCaseSettings({}));
    expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText({ code }, t())]);
  });
});
