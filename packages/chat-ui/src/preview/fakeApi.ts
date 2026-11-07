/**
 * The previews talk to no server: `fetch` is answered from sample.ts. A request it doesn't know is
 * answered 404 and named in the console, so a preview that needs more data says so. A write (POST, PUT,
 * PATCH, DELETE) it doesn't know is answered with what was sent, so a button can be pressed.
 */
import { routes, UPLOADS, type Route } from "./sample";

/** Requests the preview should leave unanswered (a screen kept in its loading state). */
const held = new Set<string>();
export const hold = (pattern: string) => held.add(pattern);
/** Requests that fail as a dropped connection does ("/health": the server can't be reached). */
const failing = new Map<string, number>();  // pattern → the moment it starts failing
/** `afterMs`: answer normally for that long first (the page loads, then the server goes away, board G09). */
export const offline = (pattern = "/health", afterMs = 0) => failing.set(pattern, Date.now() + afterMs);
/** Answers that go before the sample office's own (another office, an error). */
const first: Route[] = [];
export const replace = (more: Route[]) => first.push(...more);

/** An upload (api.ts sends it with XMLHttpRequest, for its progress): answered with the job UPLOADS
 *  names for the file, as the server answers once the file has arrived. */
class SampleUpload extends EventTarget {
  upload = new EventTarget() as XMLHttpRequestUpload;
  status = 0; response: unknown = null; responseType = "";
  onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null;
  open() {}
  getResponseHeader() { return null; }
  abort() { this.onabort?.(); }
  send(form: FormData) {
    const file = form.get("file") as File | null;
    const job = file && UPLOADS[file.name];
    setTimeout(() => {
      if (!job) { console.warn(`preview: no sample upload for ${file?.name}`); this.status = 404; }
      else { this.status = 200; this.response = job; }
      this.onload?.();
    }, 50);
  }
}

export function useSampleData(): void {
  window.XMLHttpRequest = SampleUpload as unknown as typeof XMLHttpRequest;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
    if (url.origin !== window.location.origin || !/^\/(v1|auth|health)\b/.test(url.pathname)) return real(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname + url.search;
    for (const [f, from] of failing) if (path.startsWith(f) && Date.now() >= from) throw new TypeError("Failed to fetch");
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
