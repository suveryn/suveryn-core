/**
 * Waiting for one's turn (Pod check of 27 October 2026, recommendation 6): the gateway takes a limited number
 * of uploads per person per minute (suveryn-tracker#14) and answers the rest with 429 and Retry-After. A drop
 * of 38 files had 18 refused, each card saying "too many requests". The chat waits the time the gateway names
 * and sends the file again itself, so a large drop simply takes longer.
 *
 * Only the rate limit is waited for. A full reading queue ("documents are waiting") is said, as before.
 */

/** A 429 from the per-person rate limit, with the seconds the gateway asks to wait. */
export class RateLimited extends Error {
  constructor(message: string, readonly seconds: number) {
    super(message);
    this.name = "RateLimited";
  }
}

export const MAX_TURNS = 10;  // at most this many waits for one file: 10 minutes at the gateway's 60 s window
const MAX_WAIT_S = 120;

/** Resolves after `ms`, or rejects with an AbortError when `signal` aborts (the card's ×). */
export function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("cancelled", "AbortError")); return; }
    const timer = setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
    const stop = () => { clearTimeout(timer); reject(new DOMException("cancelled", "AbortError")); };
    signal?.addEventListener("abort", stop, { once: true });
  });
}

/** `send()`, sent again after each rate-limit refusal once its wait is over; `onWait` says it is waiting. */
export async function inTurn<T>(send: () => Promise<T>, onWait: (seconds: number) => void, signal?: AbortSignal,
                                wait: (ms: number, signal?: AbortSignal) => Promise<void> = pause): Promise<T> {
  for (let turn = 0; ; turn++) {
    try {
      return await send();
    } catch (e) {
      if (!(e instanceof RateLimited) || turn + 1 >= MAX_TURNS) throw e;
      const seconds = Math.min(Math.max(1, e.seconds), MAX_WAIT_S);
      onWait(seconds);
      await wait(seconds * 1000, signal);
    }
  }
}
