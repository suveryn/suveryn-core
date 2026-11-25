/**
 * How generated code (src/generated, written by Orval from the gateway's description) reaches the gateway: one
 * `fetch`, same origin, and the answer as it came, whatever its status. It never decides what a refusal means: a
 * screen's call goes through `answered` (src/api.ts), which does.
 */
import { t } from "../i18n";

/** The gateway couldn't be reached, or the connection broke while its answer came: in the reader's language, never
 *  the browser's own English ("Failed to fetch", "NetworkError when attempting to fetch resource", "Load failed").
 *  A `TypeError`, as the browser's own is, so what tells a broken connection from a refusal still does (the code
 *  review of 25 November, suveryn-tracker#262). */
export class Unreachable extends TypeError {}

/** `fetch`, its failure to connect said as `serverUnreachable`. */
export async function reach(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (e) {
    throw e instanceof TypeError ? new Unreachable(t().serverUnreachable) : e;  // a stop (AbortError) stays itself
  }
}

/** An answer as generated code hands it on: `data` is the body read as JSON, or `undefined` when it isn't JSON;
 *  `empty`: there was no body at all. */
export type Answer = { data: unknown; status: number; headers: Headers; empty?: boolean };

export async function gatewayFetch<T>(url: string, options: RequestInit): Promise<T> {
  const response = await reach(url, options);
  const text = await response.text();
  let data: unknown;
  if (text && /^application\/([\w.-]+\+)?json\b/i.test(response.headers.get("Content-Type") ?? "")) {
    try { data = JSON.parse(text); } catch { /* cut short: not an answer */ }
  }
  return { data, status: response.status, headers: response.headers, empty: text === "" } as T;
}
