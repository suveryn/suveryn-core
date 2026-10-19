/**
 * What the Documents overview says of a row (docs/design/sidebar.md §4), kept apart from the page so it
 * can be tested: a document's status, and whether its menu offers *Delete*. The server still decides
 * (routes/documents.py); this only keeps the menu honest, an action without the right shown disabled.
 */
import type { Case } from "../api";
import { originKind } from "./origin";
import type { AllDocument } from "../components/Sidebar";

export type DocStatus = "ready" | "review" | "processing" | "failed" | "closed" | "notSource" | "confirmed";

/** Case closed before anything else; then sūveryn's own output (never a source, unless a playbook's
 *  result someone confirmed); then whether pages need checking. Uploads still being read are jobs. */
export function documentStatus(d: AllDocument, kase: Pick<Case, "state"> | undefined | null): DocStatus {
  if (kase?.state === "closed") return "closed";
  if (originKind(d) !== "source") return d.origin === "playbook" && d.provenance?.confirmed ? "confirmed" : "notSource";
  return d.status === "needs_review" ? "review" : "ready";
}

/** The server's rule: anything in one's own space; in an open case, its manager; a contributor only
 *  their own upload still waiting for a choice, or an answer they saved there. Never in a closed case. */
export function mayDeleteDocument(d: AllDocument, kase: Pick<Case, "state" | "my_role"> | null, me: string): boolean {
  if (!d.case_id) return true;
  if (!kase || kase.state === "closed") return false;
  if (kase.my_role === "manager") return true;
  return kase.my_role === "contributor" && !!me && d.uploaded_by === me && (originKind(d) === "pending" || d.origin === "answer");
}
