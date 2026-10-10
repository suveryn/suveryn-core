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

/** Records a redirect (for the loop guard) and says whether it may happen. */
export function claimRedirect(now = Date.now()): boolean {
  if (!shouldRedirect(now, read())) return false;
  try { sessionStorage.setItem(KEY, String(now)); } catch { /* without storage the guard is off; the screen stays as fallback */ }
  return true;
}

/** Signed in: the next sign-out may redirect straight away again. */
export function clearRedirect(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}
