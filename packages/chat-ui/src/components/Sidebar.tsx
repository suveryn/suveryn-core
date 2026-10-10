/**
 * The sidebar: saved conversations, then the document library (stored documents, uploads in
 * progress and failed uploads). A document in needs_review is usable but names the pages to check.
 * Deleting a conversation or a document asks for confirmation first.
 */
import { AlertTriangle, BarChart3, FileText, Loader2, LogOut, MessageSquare, Plus, Shield, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { reviewPages, type ConversationSummary, type Job, type Me, type StoredDocument } from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { compact } from "../lib/usage";
import { pageList, reviewHint } from "../lib/review";
import { Lockup } from "./Brand";
import { LanguagePicker } from "./LanguagePicker";

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
  tokensToday: number | null;   // the user's own tokens today; null when usage isn't available
  onOpenUsage: () => void;
  admin: boolean;               // shows the administration link
  onOpenAdmin: () => void;
};

/** Library of stored documents. Clicking one adds it to the next message as an attachment. */
export function Sidebar({ documents, jobs, available, unavailableReason, inConversation, onNewChat, onUse, onDelete,
                         user, onSignOut, conversations, currentConversation, historyNote, onOpenConversation,
                         onDeleteConversation, tokensToday, onOpenUsage, admin, onOpenAdmin }: Props) {
  const m = useT();
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <aside className="sidebar">
      <Lockup />
      <button type="button" className="button-primary" onClick={onNewChat}>
        <Plus size={16} aria-hidden /> {m.newChat}
      </button>

      <section className="library history" aria-labelledby="history-title">
        <h2 id="history-title" className="label">{m.conversations}</h2>
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
                  <button type="button" className="link-danger" onClick={() => { setConfirming(null); onDeleteConversation(c.id); }}>{m.delete}</button>
                  <button type="button" className="link" onClick={() => setConfirming(null)}>{m.keep}</button>
                </span>
              ) : (
                <button type="button" className="icon-button small" onClick={() => setConfirming(c.id)}
                        aria-label={m.deleteConversationLabel(c.title)} title={m.deleteConversationTitle}>
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        {!historyNote && conversations.length === 0 && (
          <p className="caption">{m.conversationsEmpty}</p>
        )}
      </section>

      <section className="library" aria-labelledby="library-title">
        <h2 id="library-title" className="label">{m.documents}</h2>
        {!available && <p className="caption">{unavailableReason}</p>}
        <ul>
          {jobs.map((j) => (
            <li key={j.id} className="doc doc-pending">
              {j.status === "failed" ? <XCircle size={15} aria-hidden /> : <Loader2 size={15} className="spin" aria-hidden />}
              <span className="doc-name" title={j.filename}>{j.filename}</span>
              <span className="doc-meta">{j.status === "failed" ? m.jobFailed : j.status === "queued" ? m.jobQueued : m.jobProcessing}</span>
            </li>
          ))}
          {documents.map((d) => (
            <li key={d.id} className="doc">
              <button type="button" className="doc-use" onClick={() => onUse(d)} disabled={inConversation.has(d.id)}
                      title={inConversation.has(d.id) ? m.alreadyInConversation :
                             d.status === "needs_review" ? m.useInConversationReview(reviewHint(reviewPages(d.warnings))) :
                             m.useInConversation}>
                {d.status === "needs_review" ? <AlertTriangle size={15} aria-hidden /> : <FileText size={15} aria-hidden />}
                <span className="doc-name">{d.filename}</span>
                <span className="doc-meta">
                  {m.pages(d.pages)}
                  {d.status === "needs_review" &&
                    (reviewPages(d.warnings).length ? m.checkPages(pageList(reviewPages(d.warnings))) : m.checkNeeded)}
                  {inConversation.has(d.id) && m.inUse}
                </span>
              </button>
              {confirming === d.id ? (
                <span className="doc-confirm">
                  <button type="button" className="link-danger" onClick={() => { setConfirming(null); onDelete(d); }}>{m.delete}</button>
                  <button type="button" className="link" onClick={() => setConfirming(null)}>{m.keep}</button>
                </span>
              ) : (
                <button type="button" className="icon-button small" onClick={() => setConfirming(d.id)}
                        aria-label={m.deleteDocumentLabel(d.filename)} title={m.deleteDocumentTitle}>
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        {available && documents.length === 0 && jobs.length === 0 && (
          <p className="caption">{m.documentsEmpty}</p>
        )}
      </section>

      <div className="sidebar-foot">
        <div className="user">
          <span className="user-name" title={user.username}>{user.name}</span>
          <button type="button" className="link" onClick={onSignOut}><LogOut size={14} aria-hidden /> {m.signOut}</button>
        </div>
        {tokensToday !== null && (
          <button type="button" className="link usage-counter" onClick={onOpenUsage} title={m.tokensTodayTitle}>
            <BarChart3 size={14} aria-hidden /> {m.tokensToday(compact(tokensToday))}
          </button>
        )}
        {admin && (
          <button type="button" className="link usage-counter" onClick={onOpenAdmin}>
            <Shield size={14} aria-hidden /> {m.administration}
          </button>
        )}
        <LanguagePicker />
        <p className="caption">{m.staysOnServer}</p>
      </div>
    </aside>
  );
}
