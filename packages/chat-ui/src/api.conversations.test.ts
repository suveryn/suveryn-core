/** The conversations go through code generated from the gateway's description (suveryn-tracker#246): what each call
 *  sends, and what the gateway's real answers become for the screen. */
import { afterEach, describe, expect, it, vi } from "vitest";
import conversations from "../../api-gateway/tests/conversations_answers.json";
import { deleteAllConversations, deleteConversation, getConversation, HttpError, listAllConversations, listConversations, moveConversation,
  pinConversation, renameConversation, saveConversation, shareConversation } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { gatewayAnswers, type KeptAnswer } from "./test/gateway";
import type { Turn } from "./types";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const ID = "00000000-0000-4000-8000-0000000000a1";
const CASE = "00000000-0000-4000-8000-0000000000c1";
const TURNS = [{ id: "t1", role: "user", text: "Wat is de koopprijs?" }, { id: "t2", role: "assistant", text: "€ 345.000 [1]", status: "done" }] as Turn[];
const refused = async (answer: KeptAnswer, call: () => Promise<unknown>, status: number, code: string) => {
  gatewayAnswers(answer);
  const e = await failure(call());
  expect(e).toBeInstanceOf(HttpError);
  expect([e.status, e.problem.code, e.message]).toEqual([status, code, messageText(e.problem, t())]);
  expect(e.message.length).toBeGreaterThan(10);
};

afterEach(() => vi.unstubAllGlobals());

describe("the conversations", () => {
  it("lists them: the personal space, a case, and everywhere", async () => {
    const sent = gatewayAnswers(conversations.none, conversations.mine, conversations.all);
    expect(await listConversations()).toEqual([]);
    expect((await listConversations(CASE)).map((c) => [c.id, c.title, c.pinned, c.messages, c.case_id])).toEqual([[ID, "De koopprijs", true, 2, null]]);
    expect((await listAllConversations()).map((c) => [c.title, c.owner_name, c.shared, c.shielded, c.run_id, c.titles])).toEqual([
      ["Bob's", "Bob Janssens", true, false, null, null], ["De koopprijs", "", false, false, null, null]]);
    expect(sent).toEqual([asked("GET", "/v1/conversations"), asked("GET", `/v1/conversations?case=${CASE}`), asked("GET", "/v1/conversations?all=true")]);
  });

  it("saves one whole, in a case or not, and opens it with its turns", async () => {
    const sent = gatewayAnswers(conversations.done, conversations.done, conversations.one);
    expect(await saveConversation(ID, "Wat is de koopprijs?", TURNS)).toBeUndefined();
    expect(await saveConversation(ID, "Wat is de koopprijs?", TURNS, CASE)).toBeUndefined();
    const opened = await getConversation(ID);
    expect([opened.title, opened.turns.map((turn) => [turn.role, turn.text])]).toEqual(["Wat is de koopprijs?", TURNS.map((turn) => [turn.role, turn.text])]);
    expect(sent).toEqual([asked("PUT", `/v1/conversations/${ID}`, { title: "Wat is de koopprijs?", turns: TURNS }),
      asked("PUT", `/v1/conversations/${ID}`, { title: "Wat is de koopprijs?", turns: TURNS, case_id: CASE }), asked("GET", `/v1/conversations/${ID}`)]);
  });

  it("renames, pins, shares and moves one", async () => {
    const sent = gatewayAnswers(conversations.renamed, conversations.pinned, conversations.shared, conversations.moved);
    expect((await renameConversation(ID, "De koopprijs")).title).toBe("De koopprijs");
    expect((await pinConversation(ID, true)).pinned).toBe(true);
    expect((await shareConversation(ID, true)).shared).toBe(true);
    expect((await moveConversation(ID, CASE)).case_id).toBe(CASE);
    expect(sent).toEqual([asked("PATCH", `/v1/conversations/${ID}`, { title: "De koopprijs" }), asked("PUT", `/v1/conversations/${ID}/pin`, { pinned: true }),
      asked("POST", `/v1/conversations/${ID}/share`, { shared: true }), asked("POST", `/v1/conversations/${ID}/move`, { case_id: CASE })]);
  });

  it("deletes one, one already gone all the same, and all of them", async () => {
    const sent = gatewayAnswers(conversations.done, conversations.no_such_conversation, conversations.all_deleted);
    expect(await deleteConversation(ID)).toBeUndefined();
    expect(await deleteConversation(ID)).toBeUndefined();
    expect(await deleteAllConversations()).toBeUndefined();
    expect(sent).toEqual([asked("DELETE", `/v1/conversations/${ID}`), asked("DELETE", `/v1/conversations/${ID}`), asked("DELETE", "/v1/conversations")]);
  });

  it("an id is one part of the address, whatever is in it", async () => {
    const sent = gatewayAnswers(conversations.no_such_conversation, conversations.no_such_conversation, conversations.none);
    await failure(getConversation("a/b?c"));
    await failure(pinConversation("../x", true));
    await listConversations("a&all=true");
    expect(sent.map((s) => s.path)).toEqual(["/v1/conversations/a%2Fb%3Fc", "/v1/conversations/..%2Fx/pin", "/v1/conversations?case=a%26all%3Dtrue"]);
  });

  it("each refusal is thrown with its status, its code and the code's words", async () => {
    await refused(conversations.no_such_conversation, () => getConversation(ID), 404, "request.not_found");
    await refused(conversations.not_a_conversation_id, () => getConversation("not-an-id"), 422, "request.invalid");
    await refused(conversations.too_long, () => saveConversation(ID, "T", TURNS), 413, "conversation.too_long");
    await refused(conversations.in_a_case, () => pinConversation(ID, true), 409, "conversation.in_case");
    await refused(conversations.in_a_case, () => moveConversation(ID, CASE), 409, "conversation.in_case");
    await refused(conversations.not_allowed, () => shareConversation(ID, true), 403, "case.not_allowed");
    await refused(conversations.confidential_case, () => shareConversation(ID, true), 409, "case.strictly_confidential");
    await refused(conversations.not_allowed, () => deleteConversation(ID), 403, "case.not_allowed");
  });
});
