/**
 * The previews talk to no server: `fetch` is answered from sample.ts. A request it doesn't know is
 * answered 404 and named in the console, so a preview that needs more data says so. A write (POST, PUT,
 * PATCH, DELETE) it doesn't know is answered with what was sent, so a button can be pressed.
 */
import { routes, type Route } from "./sample";

/** Requests the preview should leave unanswered (a screen kept in its loading state). */
const held = new Set<string>();
export const hold = (pattern: string) => held.add(pattern);
/** Requests that fail as a dropped connection does ("/health": the server can't be reached). */
const failing = new Set<string>();
export const offline = (pattern = "/health") => failing.add(pattern);
/** Answers that go before the sample office's own (another office, an error). */
const first: Route[] = [];
export const replace = (more: Route[]) => first.push(...more);

export function useSampleData(): void {
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
    if (url.origin !== window.location.origin || !/^\/(v1|auth|health)\b/.test(url.pathname)) return real(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname + url.search;
    if ([...failing].some((f) => path.startsWith(f))) throw new TypeError("Failed to fetch");
    if ([...held].some((h) => path.startsWith(h))) return new Promise<Response>(() => {});
    let body: unknown = null;
    try { body = typeof init?.body === "string" ? JSON.parse(init.body) : null; } catch { /* not JSON */ }
    for (const [m, pattern, answer] of [...first, ...routes]) {
      const match = m === method ? path.match(pattern) : null;
      if (match) return Response.json(typeof answer === "function" ? answer(match, body) : answer);
    }
    if (method !== "GET") return Response.json(body ?? {});
    console.warn(`preview: no sample answer for ${method} ${path}`);
    return Response.json({ detail: "not in the preview's sample data" }, { status: 404 });
  };
}
