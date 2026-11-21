/**
 * How generated code (src/generated, written by Orval from the gateway's description) reaches the gateway: one
 * `fetch`, same origin, and the answer as it came, whatever its status. It never decides what a refusal means: a
 * screen's call goes through `answered` (src/api.ts), which does.
 */

/** An answer as generated code hands it on: `data` is the body read as JSON, or `undefined` when it isn't JSON. */
export type Answer = { data: unknown; status: number; headers: Headers };

export async function gatewayFetch<T>(url: string, options: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  let data: unknown;
  if (/^application\/([\w.-]+\+)?json\b/i.test(response.headers.get("Content-Type") ?? "")) {
    try { data = await response.json(); } catch { /* cut short: not an answer */ }
  }
  return { data, status: response.status, headers: response.headers } as T;
}
