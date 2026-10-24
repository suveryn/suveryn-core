import { describe, expect, it } from "vitest";
import type { AllDocument } from "../components/Sidebar";
import { documentStatus, mayDeleteDocument } from "./overviews";

const doc = (over: Partial<AllDocument> = {}): AllDocument => ({
  id: "d1", filename: "deed.pdf", pages: 4, ocr_pages: 0, status: "ok", warnings: [], created_at: "2026-10-01T10:00:00Z",
  origin: "uploaded", uploaded_by: "alice", source: true, case_id: "c1", ...over,
});
const open = { state: "open" as const };

describe("the Documents overview's rows (docs/design/sidebar.md §4)", () => {
  it("says a document's status", () => {
    expect(documentStatus(doc(), open)).toBe("ready");
    expect(documentStatus(doc({ status: "needs_review" }), open)).toBe("review");
    expect(documentStatus(doc({ origin: "answer", source: false }), open)).toBe("notSource");
    expect(documentStatus(doc({ origin: "playbook", source: false, provenance: { confirmed: { by: "bob", at: "2026-10-02" } } }), open)).toBe("confirmed");
    expect(documentStatus(doc({ provenance: { noticed: { ref: "A-1", kind: "answer", line: "…" } } }), open)).toBe("notSource");
    expect(documentStatus(doc({ status: "needs_review" }), { state: "closed" })).toBe("closed");  // the case first
    expect(documentStatus(doc({ case_id: null }), null)).toBe("ready");
  });

  it("offers Delete only where the server allows it", () => {
    const manager = { state: "open" as const, my_role: "manager" as const };
    const contributor = { state: "open" as const, my_role: "contributor" as const };
    const reader = { state: "open" as const, my_role: "reader" as const };
    const noticed = { provenance: { noticed: { ref: "A-1", kind: "answer" as const, line: "…" } } };
    expect(mayDeleteDocument(doc({ case_id: null }), null, "alice")).toBe(true);           // one's own space
    expect(mayDeleteDocument(doc(), manager, "bob")).toBe(true);
    expect(mayDeleteDocument(doc(), { ...manager, state: "closed" }, "bob")).toBe(false);   // never in a closed case
    expect(mayDeleteDocument(doc(), contributor, "alice")).toBe(false);                     // a source, even their own
    expect(mayDeleteDocument(doc(noticed), contributor, "alice")).toBe(true);               // their upload waiting for a choice
    expect(mayDeleteDocument(doc(noticed), contributor, "carol")).toBe(false);              // someone else's
    expect(mayDeleteDocument(doc({ origin: "answer", source: false }), contributor, "alice")).toBe(true);  // an answer they saved
    expect(mayDeleteDocument(doc({ origin: "answer", source: false }), reader, "alice")).toBe(false);
    expect(mayDeleteDocument(doc(), { state: "open", my_role: null }, "admin")).toBe(false);  // an administrator outside the case
  });
});
