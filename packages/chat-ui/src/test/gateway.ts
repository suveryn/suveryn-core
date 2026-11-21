/**
 * The gateway for a test of generated code (src/generated): `fetch` answers with what the gateway really answered,
 * kept by its own tests (packages/api-gateway/tests/described.py, `Kept`), so both halves are tested on the same
 * answers and no server runs. Each test says which answers come, in order; `sent` is what the code asked.
 */
import { vi } from "vitest";

export type KeptAnswer = { status: number; media_type: string | null; body: unknown };
export type Sent = { method: string; path: string; body: unknown; cache: RequestCache };

const response = (a: KeptAnswer) => new Response(a.body === null ? null : JSON.stringify(a.body),
  { status: a.status, headers: a.media_type ? { "Content-Type": a.media_type } : {} });

/** The next calls get these answers, in order: a kept answer, a `Response` of the test's own, or an error `fetch` throws. */
export function gatewayAnswers(...answers: (KeptAnswer | Response | Error)[]): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    sent.push({ method, path, body: typeof init.body === "string" ? JSON.parse(init.body) : null, cache: init.cache ?? "default" });
    const next = answers.shift();
    if (next === undefined) throw new Error(`the test gave no answer for ${method} ${path}`);
    if (next instanceof Error) throw next;
    return next instanceof Response ? next : response(next);
  }));
  return sent;
}
