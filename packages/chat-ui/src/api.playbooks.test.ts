/** The playbooks and their runs go through code generated from the gateway's description (suveryn-tracker#247): what
 *  each call sends, and what the gateway's real answers become for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import playbooks from "../../api-gateway/tests/playbooks_answers.json";
import { activeRuns, answerRun, casePlaybooks, caseRuns, confirmRun, getRun, HttpError, listAdminPlaybooks, runAction, sayInRun, setPlaybookActive,
  setRunFact, startRun } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers, type KeptAnswer } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const CASE = playbooks.started.body.case_id;
const RUN = playbooks.started.body.id;
const RUNS = `/v1/cases/${CASE}/playbooks/runs`;
const refused = async (answer: KeptAnswer, call: () => Promise<unknown>, status: number, code: string) => {
  gatewayAnswers(answer);
  const e = await failure(call());
  expect(e).toBeInstanceOf(HttpError);
  expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText(e.problem, t())]);
  expect(e.message.length).toBeGreaterThan(10);
};

afterEach(() => vi.unstubAllGlobals());

describe("the playbooks", () => {
  it("lists the ones that fit a case and the office's, and switches one on or off", async () => {
    const sent = gatewayAnswers(playbooks.fitting, playbooks.fitting, { ...playbooks.fitting, body: playbooks.fitting.body[0] });
    const [fits] = await casePlaybooks(CASE);
    expect([fits.slug, fits.covered, fits.active, fits.case_types, fits.lists.sellers, fits.kinds["conditions.term"]]).toEqual([
      "deed-intake", true, true, ["sale"], ["name", "address", "register"], "date"]);
    expect(fits.steps.map((s) => s.kind)).toContain("checkpoint");
    expect([fits.steps[0].by, fits.steps[0].allow_none, fits.text.nl.title, fits.text.en.labels.price]).toEqual(["anyone_in_case", false, "Akte-intake", "Price"]);
    expect((await listAdminPlaybooks()).length).toBe(1);
    expect((await setPlaybookActive("deed-intake", false)).slug).toBe("deed-intake");
    expect(sent).toEqual([asked("GET", `/v1/cases/${CASE}/playbooks`), asked("GET", "/v1/admin/playbooks"),
      asked("PUT", "/v1/admin/playbooks/deed-intake", { active: false })]);
  });
});

describe("a run", () => {
  it("starts, and is found again: by itself, among its case's, and as the live one of each case", async () => {
    const sent = gatewayAnswers(playbooks.started, playbooks.started, playbooks.runs, playbooks.active);
    const run = await startRun(CASE, "deed-intake", "nl");
    expect([run.status, run.step, run.language, run.failure, run.facts, run.facts_seq, run.turns.map((turn) => [turn.role, turn.meta])]).toEqual([
      "waiting", "agreement", "nl", null, [], 1, [["playbook", { kind: "request" }]]]);
    expect([run.steps.agreement.status, run.playbook.slug, run.conversation_id.length]).toEqual(["active", "deed-intake", 36]);
    expect((await getRun(CASE, RUN)).id).toBe(RUN);
    expect((await caseRuns(CASE)).map((r) => [r.id, r.step_kind, r.title.nl])).toEqual([[RUN, "request", "Akte-intake"]]);
    expect((await activeRuns())[CASE].step).toBe("agreement");
    expect(sent).toEqual([asked("POST", `/v1/cases/${CASE}/playbooks/deed-intake/runs`, { document_ids: [], language: "nl" }), asked("GET", `${RUNS}/${RUN}`),
      asked("GET", RUNS), asked("GET", "/v1/playbooks/runs/active")]);
  });

  it("is answered, in a step's own form or in words, and reads the facts with where they were found", async () => {
    const sent = gatewayAnswers(playbooks.asking, playbooks.asking, playbooks.asking);
    const run = await answerRun(CASE, RUN, "certificates", { none: true });
    const price = run.facts.find((f) => f.id === "price")!;
    expect([run.step, price.value, price.found, price.source, price.confirmed, price.needs, price.computed, price.alternative]).toEqual([
      "missing", "EUR 412.500,00", true, "document", null, null, null, null]);
    expect([price.citations[0].filename, typeof price.citations[0].text, Array.isArray(price.citations[0].ranges)]).toEqual(["akte.pdf", "string", true]);
    await answerRun(CASE, RUN, "missing", { facts: { cadastral: "Gent" }, text: "Gent." });
    await sayInRun(CASE, RUN, { text: "Hier is het compromis.", documents: ["d1"] });
    expect(sent).toEqual([asked("POST", `${RUNS}/${RUN}/answer`, { step_id: "certificates", none: true }),
      asked("POST", `${RUNS}/${RUN}/answer`, { step_id: "missing", facts: { cadastral: "Gent" }, text: "Gent." }),
      asked("POST", `${RUNS}/${RUN}/say`, { text: "Hier is het compromis.", documents: ["d1"] })]);
  });

  it("has a value adjusted and its facts confirmed from the screen that saw them", async () => {
    const sent = gatewayAnswers(playbooks.done, playbooks.done);
    await setRunFact(CASE, RUN, "sellers[1].name", "Jan Peeters");
    const done = await confirmRun(CASE, RUN, [{ id: "price", confirmed: "EUR 415.000,00" }], 7);
    expect([done.status, done.step, done.confirmed_by, typeof done.result_document_id, done.checks.a_seller.status]).toEqual(["done", null, "notaris.test", "string", "holds"]);
    expect(done.facts.find((f) => f.id === "price")).toMatchObject({ value: "EUR 415.000,00", confirmed: "EUR 415.000,00", by: "bob.test", source: "person" });
    expect(sent).toEqual([asked("PUT", `${RUNS}/${RUN}/facts/sellers%5B1%5D.name`, { value: "Jan Peeters" }),
      asked("PUT", `${RUNS}/${RUN}/facts`, { facts: [{ id: "price", confirmed: "EUR 415.000,00" }], seen: 7 })]);
  });

  it("is paused, resumed, stopped and cancelled, each at its own address, a cancel with its reason", async () => {
    const sent = gatewayAnswers(playbooks.started, playbooks.started, playbooks.cancelled, playbooks.cancelled);
    await runAction(CASE, RUN, "pause");
    await runAction(CASE, RUN, "resume");
    await runAction(CASE, RUN, "stop");
    const cancelled = await runAction(CASE, RUN, "cancel", "wrong file");
    expect([cancelled.status, cancelled.ended_reason, cancelled.ended_by]).toEqual(["cancelled", "wrong file", "notaris.test"]);
    expect(sent).toEqual([asked("POST", `${RUNS}/${RUN}/pause`), asked("POST", `${RUNS}/${RUN}/resume`), asked("POST", `${RUNS}/${RUN}/stop`),
      asked("POST", `${RUNS}/${RUN}/cancel`, { reason: "wrong file" })]);
  });

  it("an id is one part of the address, whatever is in it", async () => {
    const sent = gatewayAnswers(playbooks.no_such_run, playbooks.no_such_run, playbooks.no_such_run);
    await failure(getRun("a/b", "r?1"));
    await failure(startRun("c 1", "../x", "nl"));
    await failure(runAction("a/b", "r#1", "stop"));
    expect(sent.map((s) => s.path)).toEqual(["/v1/cases/a%2Fb/playbooks/runs/r%3F1", "/v1/cases/c%201/playbooks/..%2Fx/runs", "/v1/cases/a%2Fb/playbooks/runs/r%231/stop"]);
  });

  it("each refusal is thrown with its status, its code and the code's words", async () => {
    await refused(playbooks.no_such_run, () => getRun(CASE, RUN), 404, "request.not_found");
    await refused(playbooks.already_going, () => startRun(CASE, "deed-intake", "nl"), 409, "run.already_going");
    await refused(playbooks.too_many, () => startRun(CASE, "deed-intake", "nl"), 429, "request.too_many");
    await refused(playbooks.is_paused, () => answerRun(CASE, RUN, "agreement"), 409, "run.paused");
    await refused(playbooks.moved_on, () => answerRun(CASE, RUN, "read"), 409, "run.moved_on");
    await refused(playbooks.facts_changed, () => confirmRun(CASE, RUN, [], 1), 409, "run.facts_changed");
    await refused(playbooks.starter_or_manager_only, () => runAction(CASE, RUN, "stop"), 403, "run.starter_or_manager_only");
    await refused(playbooks.ended, () => runAction(CASE, RUN, "cancel", "x"), 409, "run.ended");
    await refused(playbooks.ended, () => sayInRun(CASE, RUN, { text: "x" }), 409, "run.ended");
  });

  it("an answer that was refused for its run keeps what the screen needs to open that run", async () => {
    gatewayAnswers(playbooks.already_going);
    const e = await failure(startRun(CASE, "deed-intake", "nl"));
    expect(e.problem.params.run).toBe(RUN);
  });
});
