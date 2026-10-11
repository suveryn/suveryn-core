import type { WireMessage } from "../api";
import type { Turn } from "../types";
import { stripMarkers } from "./answer";

/**
 * The earlier turns to send with a new question: only question-and-answer pairs whose answer
 * completed. A question whose answer failed (or is still streaming) is left out together with
 * that answer, so roles always alternate user/assistant; several chat templates (e.g. Mistral's)
 * reject two user messages in a row. Citation markers are stripped: they refer to the passages of
 * that earlier answer, not to the excerpts of the new one. Only the last ``MAX_HISTORY`` messages: the
 * server takes at most 200 per request (a long conversation failed after about 100 questions), and
 * older turns don't fit the model's context anyway.
 */
export const MAX_HISTORY = 40;

export function conversationHistory(turns: Turn[]): WireMessage[] {
  const out: WireMessage[] = [];
  turns.forEach((t, i) => {
    const next = turns[i + 1];
    if (t.role === "user" && next?.role === "assistant" && next.status === "done") {
      out.push({ role: "user", content: t.text }, { role: "assistant", content: stripMarkers(next.text) });
    }
  });
  return out.slice(-MAX_HISTORY);  // an even number: still starts with a question
}
