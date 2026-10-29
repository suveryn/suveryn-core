// @vitest-environment node
/**
 * The Documents overview names who added each document: the signed-in person, a member of the case,
 * or a deleted account, whose name the case keeps (round 2, finding 5).
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CaseOverview } from "../api";
import { DocumentsOverview } from "./Overviews";
import type { AllDocument } from "./Sidebar";

const doc = (over: Partial<AllDocument>): AllDocument => ({
  id: "d1", filename: "deed.pdf", pages: 4, ocr_pages: 0, status: "ok", warnings: [], created_at: "2026-10-01T10:00:00Z",
  origin: "uploaded", uploaded_by: "alice", source: true, case_id: "c1", ...over,
});
const kase = { id: "c1", reference: "TEST-1", name: "A fictional sale", state: "open", my_role: "manager",
  members: [{ user: "bob", username: "test-bob", name: "Test Bob", role: "contributor" }], last_activity_at: null, last_activity_by: "" } as unknown as CaseOverview;
const none = () => {};

describe("the Documents overview", () => {
  it("names a member, and a deleted account by the name the case keeps", () => {
    const html = renderToStaticMarkup(
      <DocumentsOverview documents={[doc({ id: "d1", uploaded_by: "bob" }), doc({ id: "d2", filename: "attest.pdf", uploaded_by: "dirk" })]}
                         jobs={[]} jobsCase={null} cases={[kase]} me={{ username: "test-alice", name: "Test Alice", sub: "alice" }}
                         departed={{ dirk: "Test Dirk" }} onOpen={none} onDelete={none} onUseAsSource={none} onDownload={none} onUpload={none} />);
    expect(html).toContain("Test Bob");
    expect(html).toContain("Test Dirk");
  });
});
