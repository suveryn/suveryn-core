/**
 * How generated code (src/generated, written by Orval from the gateway's description) reaches the gateway: one
 * `fetch`, same origin, and the answer as it came, whatever its status. It never decides what a refusal means: a
 * screen's call goes through `answered` (src/api.ts), which does.
 */

/** An answer as generated code hands it on: `data` is the body read as JSON, or `undefined` when it isn't JSON;
 *  `empty`: there was no body at all. */
export type Answer = { data: unknown; status: number; headers: Headers; empty?: boolean };

export async function gatewayFetch<T>(url: string, options: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const text = await response.text();
  let data: unknown;
  if (text && /^application\/([\w.-]+\+)?json\b/i.test(response.headers.get("Content-Type") ?? "")) {
    try { data = JSON.parse(text); } catch { /* cut short: not an answer */ }
  }
  return { data, status: response.status, headers: response.headers, empty: text === "" } as T;
}
