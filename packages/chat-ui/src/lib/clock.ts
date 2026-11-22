/**
 * The appliance's clock against this PC's (the gateway's clock.py, decision, 30 October 2026). Measured as NTP does:
 * a few round trips, the quickest one, the appliance's time against the middle of it, so the network's delay
 * doesn't count as the difference. Reported while someone is signed in, once and then every hour; the gateway
 * nudges the appliance's clock when the reports agree. Status measures it again for "Set to this PC's time".
 */

import { answered } from "../api";
import { getClock, reportClockMeasurement, type Measured } from "../generated/gateway";

export type { Measured };

const TRIES = 3;
export const REPORT_EVERY_MS = 60 * 60 * 1000;

/** One round trip's difference: the appliance's clock minus the PC's at the middle of the round trip. */
export function difference(sentAt: number, applianceAt: number, receivedAt: number): Measured {
  return { offset_ms: Math.round(applianceAt - (sentAt + receivedAt) / 2), rtt_ms: Math.max(0, Math.round(receivedAt - sentAt)) };
}

/** The quickest of the round trips: it says the most about the difference. */
export function quickest(samples: Measured[]): Measured | null {
  return samples.reduce<Measured | null>((best, s) => (best === null || s.rtt_ms < best.rtt_ms ? s : best), null);
}

export async function measureClock(): Promise<Measured | null> {
  const samples: Measured[] = [];
  for (let i = 0; i < TRIES; i++) {
    const sentAt = Date.now();
    const answer = await getClock({ cache: "no-store" });
    const receivedAt = Date.now();
    if (answer.status < 200 || answer.status >= 300) return null; // refused or down: nothing measured, and no sign-in screen
    const { now_ms } = await answered(Promise.resolve(answer)); // an answer that isn't the gateway's: thrown, as no network is
    samples.push(difference(sentAt, now_ms, receivedAt));
  }
  return quickest(samples);
}

/** Report one measurement to the gateway. */
export async function sendClock(m: Measured): Promise<void> {
  await reportClockMeasurement(m);
}

/** Measure and report; quietly nothing when that doesn't work (the clock is not the page's business). */
export async function reportClock(): Promise<void> {
  try {
    const m = await measureClock();
    if (m) await sendClock(m);
  } catch {
    // offline for a moment: the next hour's report
  }
}
