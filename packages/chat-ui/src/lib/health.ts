/**
 * What /health says about the server's PostgreSQL. The gateway's stores that live there report
 * "failed" while it can't be reached; "unavailable" means a store this server doesn't have.
 */
import type { Health } from "../api";

/** True when the stores in PostgreSQL can't reach it: the sign-in service, whose accounts are kept in
 *  the same PostgreSQL, can't sign anyone in then either (Pod check of 547f48e). */
export function databaseDown(h: Health | null): boolean {
  return !!h && [h.history, h.cases].some((s) => s?.status === "failed");
}
