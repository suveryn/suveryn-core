import { describe, expect, it } from "vitest";
import { citedNumbers, stripMarkers, toBlocks } from "./answer";
import { modelName } from "./model";
import { createSSEParser, type SSEEvent } from "./sse";

describe("SSE parser", () => {
  it("handles events split across chunks", () => {
    const got: SSEEvent[] = [];
    const p = createSSEParser((e) => got.push(e));
    p.feed('event: delta\ndata: {"text":"Een "}\n\nevent: del');
    p.feed('ta\ndata: {"text":"akte."}\n\nevent: done\ndata: {}\n\n');
    expect(got).toEqual([
      { event: "delta", data: '{"text":"Een "}' },
      { event: "delta", data: '{"text":"akte."}' },
      { event: "done", data: "{}" },
    ]);
  });
});

describe("answer rendering", () => {
  it("turns valid markers into citations and leaves invalid ones as text", () => {
    const [p] = toBlocks("De koopprijs is EUR 412.500,00 [1], zie ook [9].", 2);
    expect(p.segments).toEqual([
      { kind: "text", text: "De koopprijs is EUR 412.500,00 " },
      { kind: "cite", n: 1 },
      { kind: "text", text: ", zie ook [9]." },
    ]);
  });

  it("renders list items, bold text and headings without HTML", () => {
    const blocks = toBlocks("## Partijen\n- **Verkoper**: A [2]\n- Koper <b>x</b>", 2);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "li", "li"]);
    expect(blocks[0].segments).toEqual([{ kind: "bold", text: "Partijen" }]);
    expect(blocks[1].segments[0]).toEqual({ kind: "bold", text: "Verkoper" });
    expect(blocks[2].segments).toEqual([{ kind: "text", text: "Koper <b>x</b>" }]); // stays literal text
  });

  it("lists cited sources in order of first use", () => {
    expect(citedNumbers("a [2] b [1][2] c [5]", 3)).toEqual([2, 1]);
    expect(stripMarkers("Prijs EUR 10 [1]. Datum [2][3], ok")).toBe("Prijs EUR 10. Datum, ok");
  });
});

describe("model tag", () => {
  it("names served models without vendor logos or quantisation noise", () => {
    expect(modelName("Qwen3.8-27B-UD-Q4_K_M.gguf")).toEqual({ full: "Qwen3.8-27B", family: "Qwen" });
    expect(modelName("Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf")).toEqual({ full: "Mistral Small 3.2", family: "Mistral" });
    expect(modelName(null)).toBeNull();
  });
});
