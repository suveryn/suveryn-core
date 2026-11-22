/** The cases go through code generated from the gateway's description (suveryn-tracker#244): what each call sends,
 *  and what the gateway's real answers become for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import cases from "../../api-gateway/tests/cases_answers.json";
import { closeCase, createCase, deleteCase, getCase, handOver, HttpError, keepCase, listAdminCases, listCaseEvents, listCases,
  listCasesOverview, listCaseTypes, listMembers, pinCase, removeMember, reopenCase, setMember, updateCase } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers, type KeptAnswer } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const ID = "00000000-0000-4000-8000-0000000000c1";
const refused = async (answer: KeptAnswer, call: () => Promise<unknown>, status: number, code: string) => {
  gatewayAnswers(answer);
  const e = await failure(call());
  expect(e).toBeInstanceOf(HttpError);
  expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText(e.problem, t())]);
  expect(e.message.length).toBeGreaterThan(10);
};

afterEach(() => vi.unstubAllGlobals());

describe("the cases", () => {
  it("lists them: mine, with the closed ones when asked, the overview, the office's, and the types", async () => {
    const sent = gatewayAnswers(cases.mine, cases.mine, cases.overview, cases.office, cases.types);
    const mine = await listCases();
    expect(mine.map((c) => [c.id, c.reference, c.state, c.my_role, c.pinned, c.confidential])).toEqual([[ID, "2026/0417", "open", "manager", false, false]]);
    await listCases(true);
    const [overview] = await listCasesOverview();
    expect([overview.members.map((m) => [m.username, m.role]), overview.last_activity_by]).toEqual([[["notaris.test", "manager"], ["bob", "reader"]], "Test Notaris"]);
    const [office] = await listAdminCases();
    expect([office.manager_name, office.manager_username, office.members, office.my_role]).toEqual(["Test Notaris", "notaris.test", 1, null]);
    expect((await listCaseTypes())[0]).toEqual({ id: "sale", pack: "pack/be-notary", text: { en: "Sale", fr: "Vente", nl: "Verkoop" } });
    expect(sent).toEqual([asked("GET", "/v1/cases"), asked("GET", "/v1/cases?closed=true"), asked("GET", "/v1/cases/overview"),
      asked("GET", "/v1/admin/cases"), asked("GET", "/v1/case-types")]);
  });

  it("makes one, reads it, changes it and pins it", async () => {
    const sent = gatewayAnswers(cases.created, cases.one, cases.renamed, cases.pinned);
    const made = await createCase({ reference: "2026/0417", name: "Verkoop Kerkstraat 12", type: "sale" });
    expect([made.id, made.name, made.state, made.closed_at, made.keep_until]).toEqual([ID, "Verkoop Kerkstraat 12", "open", null, null]);
    expect((await getCase(ID)).name).toBe("Verkoop Kerkstraat 12");
    expect((await updateCase(ID, { name: "Verkoop Kerkstraat 14" })).name).toBe("Verkoop Kerkstraat 14");
    expect((await pinCase(ID, true)).pinned).toBe(true);
    expect(sent).toEqual([asked("POST", "/v1/cases", { reference: "2026/0417", name: "Verkoop Kerkstraat 12", type: "sale" }),
      asked("GET", `/v1/cases/${ID}`), asked("PATCH", `/v1/cases/${ID}`, { name: "Verkoop Kerkstraat 14" }),
      asked("PUT", `/v1/cases/${ID}/pin`, { pinned: true })]);
  });

  it("closes one, keeps it, reopens it and hands it over", async () => {
    const sent = gatewayAnswers(cases.closed, cases.kept, cases.reopened, cases.handed_over);
    const closed = await closeCase(ID);
    expect([closed.state, closed.closed_at, closed.keep_until, closed.keep]).toEqual(["closed", "2026-11-23T09:00:00Z", "2026-11-23T09:00:00Z", false]);
    expect((await keepCase(ID, { keep: true })).keep).toBe(true);
    expect((await reopenCase(ID)).state).toBe("open");
    expect((await handOver(ID, "bob-sub")).manager).toBe("bob-sub");
    expect(sent).toEqual([asked("POST", `/v1/cases/${ID}/close`), asked("POST", `/v1/cases/${ID}/keep`, { keep: true }),
      asked("POST", `/v1/cases/${ID}/reopen`), asked("POST", `/v1/cases/${ID}/handover`, { user: "bob-sub" })]);
  });

  it("its members and its access log", async () => {
    const sent = gatewayAnswers(cases.members, cases.member_added, cases.events);
    expect((await listMembers(ID)).map((m) => [m.name, m.role, m.admin, m.avatar])).toEqual([
      ["Test Notaris", "manager", false, null], ["Bob Janssens", "reader", false, null]]);
    expect(await setMember(ID, "bob-sub", "reader")).toMatchObject({ user: "bob-sub", username: "bob", role: "reader" });
    const [event] = await listCaseEvents(ID);
    expect(event).toEqual({ id: 0, user: "alice-sub", name: "Alice Peeters", at: "2026-11-23T09:00:00Z", action: "member_added",
      detail: { role: "reader", user: "bob-sub" } });
    expect(sent).toEqual([asked("GET", `/v1/cases/${ID}/members`), asked("PUT", `/v1/cases/${ID}/members/bob-sub`, { role: "reader" }),
      asked("GET", `/v1/cases/${ID}/events`)]);
  });

  it("removes a member or the case, and one already gone is removed all the same", async () => {
    const sent = gatewayAnswers(cases.done, cases.done, cases.no_such_case, cases.no_such_case);
    expect(await removeMember(ID, "bob-sub")).toBeUndefined();
    expect(await deleteCase(ID)).toBeUndefined();
    expect(await removeMember(ID, "bob-sub")).toBeUndefined();
    expect(await deleteCase(ID)).toBeUndefined();
    expect(sent.slice(0, 2)).toEqual([asked("DELETE", `/v1/cases/${ID}/members/bob-sub`), asked("DELETE", `/v1/cases/${ID}`)]);
  });

  it("an id is one part of the address, whatever is in it", async () => {
    const sent = gatewayAnswers(cases.no_such_case, cases.no_such_case, cases.no_such_case);
    await failure(getCase("a/b?c"));
    await failure(setMember("../x", "u/1", "reader"));
    await removeMember("a b", "u?1");
    expect(sent.map((s) => s.path)).toEqual(["/v1/cases/a%2Fb%3Fc", "/v1/cases/..%2Fx/members/u%2F1", "/v1/cases/a%20b/members/u%3F1"]);
  });

  it("each refusal is thrown with its status, its code and the code's words", async () => {
    await refused(cases.reference_taken, () => createCase({ reference: "2026/0417", name: "N", type: "sale" }), 409, "case.reference_exists");
    await refused(cases.no_such_case, () => getCase(ID), 404, "case.not_found");
    await refused(cases.not_allowed, () => updateCase(ID, { name: "N" }), 403, "case.not_allowed");
    await refused(cases.already_closed, () => closeCase(ID), 403, "case.closed");
    await refused(cases.still_open, () => keepCase(ID, { keep: true }), 403, "request.forbidden");
    await refused(cases.nothing_to_change, () => keepCase(ID, {}), 422, "request.invalid");
    await refused(cases.not_an_administrator, () => listAdminCases(), 403, "request.forbidden");
    await refused(cases.not_allowed, () => removeMember(ID, "bob-sub"), 403, "case.not_allowed");
    await refused(cases.not_allowed, () => deleteCase(ID), 403, "case.not_allowed");
  });
});
