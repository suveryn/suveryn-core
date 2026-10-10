/**
 * The sidebar: saved conversations, then the document library (stored documents, uploads in
 * progress and failed uploads). A document in needs_review is usable but names the pages to check.
 * Deleting a conversation or a document asks for confirmation first.
 */
import { AlertTriangle, FileText, Loader2, LogOut, MessageSquare, Plus, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { reviewPages, type ConversationSummary, type Job, type Me, type StoredDocument } from "../api";
import { dayLabel } from "../lib/conversations";
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
  user: Me;
  onSignOut: () => void;
  conversations: ConversationSummary[];
  currentConversation: string;
  historyNote: string | null;   // why conversations aren't saved, if they aren't
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
};

/** Library of stored documents. Clicking one adds it to the next message as an attachment. */
export function Sidebar({ documents, jobs, available, unavailableReason, inConversation, onNewChat, onUse, onDelete,
                         user, onSignOut, conversations, currentConversation, historyNote, onOpenConversation,
                         onDeleteConversation }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <aside className="sidebar">
      <Lockup />
      <button type="button" className="button-primary" onClick={onNewChat}>
        <Plus size={16} aria-hidden /> New chat
      </button>

      <section className="library history" aria-labelledby="history-title">
        <h2 id="history-title" className="label">Conversations</h2>
        {historyNote && <p className="caption">{historyNote}</p>}
        <ul>
          {conversations.map((c) => (
            <li key={c.id} className={`doc${c.id === currentConversation ? " doc-current" : ""}`}>
              <button type="button" className="doc-use" onClick={() => onOpenConversation(c.id)}
                      aria-current={c.id === currentConversation ? "true" : undefined}>
                <MessageSquare size={15} aria-hidden />
                <span className="doc-name" title={c.title}>{c.title}</span>
                <span className="doc-meta">{dayLabel(c.updated_at)}</span>
              </button>
              {confirming === c.id ? (
                <span className="doc-confirm">
                  <button type="button" className="link-danger" onClick={() => { setConfirming(null); onDeleteConversation(c.id); }}>Delete</button>
                  <button type="button" className="link" onClick={() => setConfirming(null)}>Keep</button>
                </span>
              ) : (
                <button type="button" className="icon-button small" onClick={() => setConfirming(c.id)}
                        aria-label={`Delete the conversation "${c.title}"`} title="Delete this conversation">
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        {!historyNote && conversations.length === 0 && (
          <p className="caption">Your conversations are saved here after each answer.</p>
        )}
      </section>

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

      <div className="sidebar-foot">
        <div className="user">
          <span className="user-name" title={user.username}>{user.name}</span>
          <button type="button" className="link" onClick={onSignOut}><LogOut size={14} aria-hidden /> Sign out</button>
        </div>
        <p className="caption">Documents and answers stay on this server.</p>
      </div>
    </aside>
  );
}
