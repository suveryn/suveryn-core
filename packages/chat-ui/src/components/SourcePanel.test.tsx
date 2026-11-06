// @vitest-environment node
/**
 * Board G11: the source panel opens the document as uploaded, a PDF at the cited page, in a new tab; a document
 * stored before files were kept still offers the passage's download.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AssistantTurn } from "../types";
import { SourcePanel } from "./Messages";

const turn = (page: number | null): AssistantTurn => ({
  id: "t1", role: "assistant", text: "The price is EUR 300,000 [1].", status: "done", grounded: true,
  citations: [{ text: "The price is EUR 300,000.", source: { document_id: "d1", page, location: page ? `p. ${page}` : "" } }],
});
const none = () => {};
const panel = (page: number | null, kept: Set<string>) => renderToStaticMarkup(
  <SourcePanel turn={turn(page)} open={{ n: 1, occ: null }} filenames={new Map([["d1", "deed.pdf"]])} caseRef="TEST-1"
               kept={kept} caseId="c1" onSource={none} onClose={none} />);

describe("the source panel's document link", () => {
  it("opens a kept PDF at the cited page, in a new tab, in the case", () => {
    const html = panel(3, new Set(["d1"]));
    expect(html).toContain('href="/v1/documents/d1/original?case=c1#page=3"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("Open document at p. 3");
    expect(html).not.toContain("Download");
  });
  it("says Open document for a file without pages", () => {
    expect(panel(null, new Set(["d1"]))).toContain(">Open document<");
  });
  it("offers the passage's download when the file isn't kept", () => {
    const html = panel(3, new Set());
    expect(html).not.toContain("/original");
    expect(html).toContain("Download");
  });
});
