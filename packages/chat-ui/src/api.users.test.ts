/** The accounts, the office's people and pictures go through code generated from the gateway's description
 *  (suveryn-tracker#241): what each call sends, and what the gateway's real answers become for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import users from "../../api-gateway/tests/users_answers.json";
import { accountDeletion, addAccount, deleteAccount, departedNames, HttpError, listAccountEvents, listAccounts, removeMyAvatar,
  resetAccountPassword, resetAccountTwoStep, searchUsers, setAccountAdmin, setAccountEnabled, setMyAvatar, signAccountOut } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers, type KeptAnswer } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const SUB = "00000000-0000-4000-8000-000000000001";
const refused = async (answer: KeptAnswer, call: () => Promise<unknown>, status: number, code: string) => {
  gatewayAnswers(answer);
  const e = await failure(call());
  expect(e).toBeInstanceOf(HttpError);
  expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText(e.problem, t())]);
  expect(e.message.length).toBeGreaterThan(10);
};

afterEach(() => vi.unstubAllGlobals());

describe("the accounts", () => {
  it("lists them, and what happened to them", async () => {
    const sent = gatewayAnswers(users.accounts, users.events);
    const list = await listAccounts();
    expect(list.users.map((u) => [u.name, u.admin, u.enabled, u.last_sign_in_unknown])).toEqual([
      ["Alice Admin", true, true, true], ["Bob Peeters", false, true, false], ["Carol Claes", false, true, true]]);
    expect(list.users[1].last_sign_in).toMatch(/^2026-10-26T/);
    expect((await listAccountEvents(5)).map((e) => e.kind)).toContain("switched_off");
    expect(sent).toEqual([asked("GET", "/v1/admin/users"), asked("GET", "/v1/admin/users/events?limit=5")]);
  });

  it("adds one with a temporary password to pass on, and resets a password the same way", async () => {
    const sent = gatewayAnswers(users.added, users.password_reset);
    const added = await addAccount("Jonas Claes", "jonas.c@office.test", false);
    expect([added.user.sub, added.user.name, added.password, added.address]).toEqual([SUB, "Jonas Claes", users.added.body.password, users.added.body.address]);
    expect((await resetAccountPassword(SUB)).password).toBe(users.password_reset.body.password);
    expect(sent).toEqual([asked("POST", "/v1/admin/users", { name: "Jonas Claes", email: "jonas.c@office.test", admin: false }),
      asked("POST", `/v1/admin/users/${SUB}/password`)]);
  });

  it("changes one: administrator or not, on or off, and what is done with nothing to read", async () => {
    const sent = gatewayAnswers(users.made_administrator, users.switched_off, users.done, users.done, users.deletion, users.done);
    expect((await setAccountAdmin(SUB, true)).admin).toBe(true);
    expect((await setAccountEnabled(SUB, false)).enabled).toBe(false);
    expect(await resetAccountTwoStep(SUB)).toBeUndefined();
    expect(await signAccountOut(SUB)).toBeUndefined();
    expect(await accountDeletion(SUB)).toEqual({ documents: 0, conversations: 0, shared_conversations: 0 });
    expect(await deleteAccount(SUB)).toBeUndefined();
    expect(sent).toEqual([
      asked("PUT", `/v1/admin/users/${SUB}/admin`, { admin: true }), asked("PUT", `/v1/admin/users/${SUB}/enabled`, { enabled: false }),
      asked("POST", `/v1/admin/users/${SUB}/two-step`), asked("POST", `/v1/admin/users/${SUB}/sign-out`),
      asked("GET", `/v1/admin/users/${SUB}/deletion`), asked("DELETE", `/v1/admin/users/${SUB}`)]);
  });

  it("an id is one part of the address, whatever is in it", async () => {
    const sent = gatewayAnswers(users.no_such_account, users.no_such_account);
    await failure(deleteAccount("a/b?c"));
    await failure(accountDeletion("../x"));
    expect(sent.map((s) => s.path)).toEqual(["/v1/admin/users/a%2Fb%3Fc", "/v1/admin/users/..%2Fx/deletion"]);
  });

  it("each refusal is thrown with its status, its code and the code's words", async () => {
    await refused(users.email_exists, () => addAccount("J", "jonas.c@office.test", false), 409, "account.email_exists");
    await refused(users.last_administrator, () => setAccountAdmin("a", false), 409, "account.last_administrator");
    await refused(users.own_account, () => setAccountEnabled("a", false), 409, "account.own_account");
    await refused(users.not_switched_off, () => accountDeletion(SUB), 409, "account.not_switched_off");
    await refused(users.not_switched_off, () => deleteAccount(SUB), 409, "account.not_switched_off");
    await refused(users.no_such_account, () => resetAccountPassword("gone"), 404, "request.not_found");
    await refused(users.not_an_administrator, () => listAccounts(), 403, "request.forbidden");
  });
});

describe("the office's people", () => {
  it("are searched by a word, each with their picture's ETag or none", async () => {
    const sent = gatewayAnswers(users.people, users.departed);
    expect((await searchUsers("e é&=")).map((p) => [p.name, p.avatar, p.admin])).toEqual([["Bob Peeters", "bobs", false], ["Carol Claes", null, false]]);
    expect(await departedNames()).toEqual({ [SUB]: "Jonas Claes" });
    expect(sent).toEqual([asked("GET", "/v1/users?q=e+%C3%A9%26%3D"), asked("GET", "/v1/users/departed")]);
  });

  it("says in words when the directory is away", async () => {
    await refused(users.directory_away, () => searchUsers("b"), 503, "auth.unavailable");
  });
});

describe("the caller's own picture", () => {
  it("is sent as the image it is, and gives its new ETag; removing it is done with nothing to read", async () => {
    const sent = gatewayAnswers(users.picture_set, users.done);
    expect(await setMyAvatar(new Blob(["an image"], { type: "image/png" }))).toBe("new1");
    expect(await removeMyAvatar()).toBeUndefined();
    expect(sent).toEqual([asked("PUT", "/v1/me/avatar", "an image"), asked("DELETE", "/v1/me/avatar")]);
  });

  it("each refusal is thrown with the code's words", async () => {
    await refused(users.picture_too_large, () => setMyAvatar(new Blob(["x"])), 413, "user.picture_too_large");
    await refused(users.no_picture_sent, () => setMyAvatar(new Blob([])), 415, "request.unsupported");
  });
});
