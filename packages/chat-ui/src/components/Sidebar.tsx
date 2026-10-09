/**
 * The document library: stored documents, uploads in progress and failed uploads. A document in
 * needs_review is usable but names the pages to check. Deleting asks for confirmation first.
 */
import { AlertTriangle, FileText, Loader2, Plus, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { reviewPages, type Job, type StoredDocument } from "../api";
import { pageList, reviewHint } from "../lib/review";
import { Lockup } from "./Brand";

type Props = {
  documents: StoredDocument[];
  jobs: Job[];
  available: boolean;           // document handling is ready on the server
  unavailableReason: string | null;
  inConversation: Set<string>;  // document ids already used in this conversation
  onNewChat: () => void;
  onUse: (doc: StoredDocument) => void;
  onDelete: (doc: StoredDocument) => void;
};

/** Library of stored documents. Clicking one adds it to the next message as an attachment. */
export function Sidebar({ documents, jobs, available, unavailableReason, inConversation, onNewChat, onUse, onDelete }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <aside className="sidebar">
      <Lockup />
      <button type="button" className="button-primary" onClick={onNewChat}>
        <Plus size={16} aria-hidden /> New chat
      </button>

      <section className="library" aria-labelledby="library-title">
        <h2 id="library-title" className="label">Documents</h2>
        {!available && <p className="caption">{unavailableReason}</p>}
        <ul>
          {jobs.map((j) => (
            <li key={j.id} className="doc doc-pending">
              {j.status === "failed" ? <XCircle size={15} aria-hidden /> : <Loader2 size={15} className="spin" aria-hidden />}
              <span className="doc-name" title={j.filename}>{j.filename}</span>
              <span className="doc-meta">{j.status === "failed" ? "Couldn't be read" : j.status === "queued" ? "Waiting…" : "Reading…"}</span>
            </li>
          ))}
          {documents.map((d) => (
            <li key={d.id} className="doc">
              <button type="button" className="doc-use" onClick={() => onUse(d)} disabled={inConversation.has(d.id)}
                      title={inConversation.has(d.id) ? "Already in this conversation" :
                             d.status === "needs_review" ? `Use in this conversation. ${reviewHint(reviewPages(d.warnings))}` :
                             "Use in this conversation"}>
                {d.status === "needs_review" ? <AlertTriangle size={15} aria-hidden /> : <FileText size={15} aria-hidden />}
                <span className="doc-name">{d.filename}</span>
                <span className="doc-meta">
                  {d.pages} {d.pages === 1 ? "page" : "pages"}
                  {d.status === "needs_review" &&
                    (reviewPages(d.warnings).length ? ` · check ${pageList(reviewPages(d.warnings))}` : " · check needed")}
                  {inConversation.has(d.id) && " · in use"}
                </span>
              </button>
              {confirming === d.id ? (
                <span className="doc-confirm">
                  <button type="button" className="link-danger" onClick={() => { setConfirming(null); onDelete(d); }}>Delete</button>
                  <button type="button" className="link" onClick={() => setConfirming(null)}>Keep</button>
                </span>
              ) : (
                <button type="button" className="icon-button small" onClick={() => setConfirming(d.id)}
                        aria-label={`Delete ${d.filename}`} title="Delete from this server">
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        {available && documents.length === 0 && jobs.length === 0 && (
          <p className="caption">No documents yet. Attach a PDF to a message to add one.</p>
        )}
      </section>

      <p className="caption sidebar-foot">Documents and answers stay on this server.</p>
    </aside>
  );
}
