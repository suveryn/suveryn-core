/**
 * The previews talk to no server: `fetch` is answered from sample.ts. A path it doesn't know is
 * answered 404 and named in the console, so a preview that needs more data says so.
 */
import { answer } from "./sample";

export function useSampleData(): void {
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
    if (url.origin !== window.location.origin || !/^\/(v1|auth|health)\b/.test(url.pathname)) return real(input, init);
    const key = `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}`;
    if (key in answer) return Response.json(answer[key]);
    console.warn(`preview: no sample answer for ${key}`);
    return Response.json({ detail: "not in the preview's sample data" }, { status: 404 });
  };
}
