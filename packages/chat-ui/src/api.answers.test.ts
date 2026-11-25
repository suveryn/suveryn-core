/** Who is signed in, signing out, and an answer as a stream go through code generated from the gateway's description
 *  (suveryn-tracker#249). The stream keeps its own reader (the generated call reads an answer whole): to the
 *  generated address, with the generated body and events. Tested on the gateway's real answers and events. */
import { afterEach, describe, expect, it, vi } from "vitest";
import answers from "../../api-gateway/tests/answers_answers.json";
import auth from "../../api-gateway/tests/auth_answers.json";
import { ANSWER_EVENTS, askInConversation, CONVERSATION_EVENTS, getMe, HttpError, signOut, StreamFailure, type AnswerHandlers, type ChatResponse,
  type Citation, type StreamStatus } from "./api";
import { messageText } from "./lib/messages";
import { t } from "./i18n";
import { eventStream, gatewayAnswers } from "./test/gateway";

const failure = async (call: Promise<unknown>) => call.then(() => { throw new Error("it didn't fail"); }, (e) => e);
const asked = (method: string, path: string, body: unknown = null) => ({ method, path, body, cache: "default" });
const stream = eventStream;

afterEach(() => vi.unstubAllGlobals());

describe("who is signed in", () => {
  it("is the person, nobody, or not known while the sign-in service is away", async () => {
    const sent = gatewayAnswers(auth.me, auth.nobody, auth.sign_in_away);
    const me = await getMe();
    expect(me).toEqual({ username: "notaris.test", name: "Test Notaris", sub: "user-1", admin: false, office_wide: false, cases_keep: "manual", avatar: null,
      account_url: "http://keycloak.test/realms/suveryn/account", office_name: null, admin_console_url: null });
    expect(await getMe()).toBeNull();
    const away = await failure(getMe());
    expect([away instanceof HttpError, away.message]).toEqual([false, messageText({ kind: "unavailable", code: "auth.unavailable", params: {} }, t())]);
    expect(sent).toEqual(Array(3).fill(asked("GET", "/auth/me")));
  });

  it("signs out here, then where the sign-in service ends its session; home when that can't be said", async () => {
    const went: string[] = [];
    vi.stubGlobal("window", { location: { assign: (to: string) => went.push(to) } });
    vi.stubGlobal("sessionStorage", { removeItem: () => {}, getItem: () => null, setItem: () => {} });
    const sent = gatewayAnswers(auth.signed_out, new Error("offline"));
    await signOut();
    await signOut();
    expect(went).toEqual([auth.signed_out.body.logout_url, "/"]);
    expect(sent).toEqual([asked("POST", "/auth/logout"), asked("POST", "/auth/logout")]);
  });
});

describe("an answer as a stream", () => {
  // read by the one reader of every answer (``readAnswer``), on the gateway's real events, kept as it streams them
  const ID = "00000000-0000-4000-8000-0000000000a1";
  const QUESTION = { text: "Wat is de koopprijs?", document_ids: ["d1"] };
  const ask = (h: Partial<AnswerHandlers> = {}) => askInConversation(ID, QUESTION, { onDelta: () => {}, ...h });

  it("is asked at the generated address, and read as it comes: what the server does, the passages, the words, the whole answer", async () => {
    const sent = gatewayAnswers(stream(answers.stream.body));
    const [steps, words, sources]: [StreamStatus["step"][], string[], Citation[][]] = [[], [], []];
    const answer = await ask({ onDelta: (text) => words.push(text), onStatus: (status) => steps.push(status.step),
                               onSources: (citations) => sources.push(citations) });
    const done = answers.stream.body.at(-1)!.data as unknown as ChatResponse;
    expect(answer).toEqual(done);
    expect([words.join(""), steps[0], sources.length, sources[0][0].source?.page]).toEqual([done.answer, "searching", 1, 2]);
    expect(sent).toEqual([asked("POST", `/v1/conversations/${ID}/questions`, QUESTION)]);
  });

  it("of a model that thinks first gives its reasoning apart, as it comes, never in the answer's words", async () => {
    gatewayAnswers(stream(answers.stream_thorough.body));
    const [thought, words]: [string[], string[]] = [[], []];
    const answer = await ask({ onDelta: (text) => words.push(text), onThinking: (text) => thought.push(text) });
    expect([thought.join(""), answer.reasoning, words.join("").includes("Article 2 gives"), answer.answer]).toEqual([
      "Article 2 gives the price.", "Article 2 gives the price.", false, words.join("")]);
  });

  it("that can't be completed fails with why, as the code's words, and keeps the message itself", async () => {
    gatewayAnswers(stream(answers.stream_failed.body));
    const e = await failure(ask());
    expect(e).toBeInstanceOf(StreamFailure);
    expect([e.failure, e.message]).toEqual([{ kind: "unavailable", code: "document.unavailable", params: {} },
      messageText({ kind: "unavailable", code: "document.unavailable", params: {} }, t())]);
  });

  it("that breaks off before its end is a failure, never half an answer", async () => {
    gatewayAnswers(stream(answers.stream.body.slice(0, -1)));
    expect((await failure(ask())).message).toBe(t().streamCutOff);
  });

  it("that is refused before it starts is thrown with its status, its code and the code's words", async () => {
    for (const [answer, status, code] of [[answers.no_such_document, 404, "answer.document_not_found"], [answers.no_such_model, 422, "model.not_found"],
      [answers.too_many, 429, "request.too_many"]] as const) {
      gatewayAnswers(answer);
      const e = await failure(ask());
      expect([e instanceof HttpError, e.status, e.problem.code, e.message]).toEqual([true, status, code, messageText(e.problem, t())]);
    }
  });

  it("has only the events the gateway's description names (api.conversations.test.ts holds the list to it)", () => {
    const said = [answers.stream, answers.stream_thorough, answers.stream_failed].flatMap((a) => a.body.map((e) => e.event));
    expect(said.filter((name) => !CONVERSATION_EVENTS.includes(name))).toEqual([]);
    expect(ANSWER_EVENTS.every((name) => CONVERSATION_EVENTS.includes(name))).toBe(true);
  });
});
