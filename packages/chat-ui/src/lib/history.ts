import type { WireMessage } from "../api";
import type { Turn } from "../types";

/**
 * The earlier turns to send with a new question: only question-and-answer pairs whose answer
 * completed. A question whose answer failed (or is still streaming) is left out together with
 * that answer, so roles always alternate user/assistant; several chat templates (e.g. Mistral's)
 * reject two user messages in a row. Answers go with their citation markers: the server shows them to
 * the model as [*] (they refer to that answer's passages, not to the new excerpts), so it sees cited
 * answers; stripped, it copied their uncited style and follow-ups cited nothing. Only the last ``MAX_HISTORY`` messages: the
 * server takes at most 200 per request (a long conversation failed after about 100 questions), and
 * older turns don't fit the model's context anyway.
 */
export const MAX_HISTORY = 40;

export function conversationHistory(turns: Turn[]): WireMessage[] {
  const out: WireMessage[] = [];
  turns.forEach((t, i) => {
    const next = turns[i + 1];
    if (t.role === "user" && next?.role === "assistant" && next.status === "done") {
      out.push({ role: "user", content: t.text }, { role: "assistant", content: next.text });
    }
  });
  return out.slice(-MAX_HISTORY);  // an even number: still starts with a question
}
