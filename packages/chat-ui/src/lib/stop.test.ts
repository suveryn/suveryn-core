import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat, type Citation } from "../api";
import type { AssistantTurn, Turn } from "../types";
import { fromSaved, toSaved } from "./conversations";
import { conversationHistory } from "./history";

const citation: Citation = { text: "The price is EUR 300,000.", source: { document_id: "d1", page: 2, location: "p. 2" } };

/** A streamed answer that writes its passages and two words, then waits for more until it is aborted. */
function endlessAnswer() {
  const encoder = new TextEncoder();
  return vi.fn(async (_url: string, init: RequestInit) => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`event: status\ndata: {"step":"searching"}\n\n`));
        controller.enqueue(encoder.encode(`event: sources\ndata: ${JSON.stringify({ citations: [citation] })}\n\n`));
        controller.enqueue(encoder.encode(`event: delta\ndata: {"text":"The price "}\n\n`));
        controller.enqueue(encoder.encode(`event: delta\ndata: {"text":"is [1]"}\n\n`));
        init.signal?.addEventListener("abort", () => controller.error(new DOMException("The user aborted a request.", "AbortError")));
      },
    });
    return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("stopping an answer (docs/design/sidebar.md §5)", () => {
  it("has the passages before the first word, and stops when aborted", async () => {
    vi.stubGlobal("fetch", endlessAnswer());
    const abort = new AbortController();
    let text = "";
    let sources: Citation[] = [];
    const answer = streamChat([{ role: "user", content: "What is the price?" }], ["d1"], (d) => {
      text += d;
      if (text.endsWith("[1]")) abort.abort();  // the person presses Stop
    }, abort.signal, null, undefined, null, (c) => { sources = c; });
    await expect(answer).rejects.toThrow(/abort/i);
    expect(text).toBe("The price is [1]");
    expect(sources).toEqual([citation]);  // the marker still points somewhere
  });

  it("keeps a stopped answer when saved, and leaves it out of what the model is sent next", () => {
    const stopped: AssistantTurn = { id: "a1", role: "assistant", text: "The price is [1]", citations: [citation], status: "stopped", grounded: true };
    const turns: Turn[] = [{ id: "u1", role: "user", text: "What is the price?", attachments: [] }, stopped];
    expect(fromSaved(toSaved(turns))).toEqual(turns);
    // cut off mid-sentence: the next question stands on its own
    expect(conversationHistory(turns)).toEqual([]);
  });
});
