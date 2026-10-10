/**
 * Going straight to Keycloak's login page instead of showing a sign-in screen first: Keycloak's
 * page already has the logo, tagline, language menu and form. The chat UI's own sign-in screen is
 * kept for the cases where it says something: a session that ended while the user was working
 * (an automatic redirect would discard what they were typing), sign-in being unavailable, and a
 * sign-in that didn't complete (see shouldRedirect).
 */

const KEY = "suveryn.signin-redirect";
export const LOOP_WINDOW_MS = 60_000;

/**
 * Whether to redirect to the login page now. Not again within a minute of the last redirect:
 * coming back signed out that soon means the sign-in didn't complete (e.g. the session cookie
 * wasn't kept), and redirecting again would loop.
 */
export function shouldRedirect(now: number, last: number | null): boolean {
  return last === null || now - last > LOOP_WINDOW_MS;
}

function read(): number | null {
  try {
    const v = Number(sessionStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch { return null; }
}

// A redirect already started in this page load. React runs effects twice in development
// (StrictMode), and the second run must not count as a loop: it showed the sign-in screen for a
// moment while the browser was already on its way to the login page.
let started = false;

/**
 * "go": redirect now (recorded for the loop guard); "started": already on the way, show nothing;
 * "stuck": back signed out within a minute of the last redirect, show the sign-in screen.
 */
export function claimRedirect(now = Date.now()): "go" | "started" | "stuck" {
  if (started) return "started";
  if (!shouldRedirect(now, read())) return "stuck";
  started = true;
  try { sessionStorage.setItem(KEY, String(now)); } catch { /* without storage the guard is off; the screen stays as fallback */ }
  return "go";
}

/** Signed in: the next sign-out may redirect straight away again. */
export function clearRedirect(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}
