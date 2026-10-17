/**
 * The sidebar: the cases (suveryn-tracker#10) with the personal space first, then the saved
 * conversations and the document library (stored documents, uploads in progress and failed
 * uploads) of the case or space that is open. A document in needs_review is usable but names the
 * pages to check. Deleting a conversation or a document asks for confirmation first.
 */
import { AlertTriangle, BarChart3, FileText, Folder, FolderPlus, Loader2, Lock, LogOut, MessageSquare, Plus, Shield, Trash2, User, Users, XCircle } from "lucide-react";
import { useState } from "react";
import { fateLabel } from "./CaseState";
import { reviewPages, type Case, type ConversationSummary, type Job, type Me, type StoredDocument } from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { compact } from "../lib/usage";
import { pageList, reviewHint } from "../lib/review";
import { Lockup } from "./Brand";
import { LanguagePicker } from "./LanguagePicker";
import { Button, IconButton, SearchField, SelectList, TextButton } from "../ui";

const SEARCH_FROM = 6;  // cases: a search box once the list is longer than this
const MY_SPACE = "my-space";

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
  me: string;                   // the signed-in user's id: whose conversations are "mine" (stage 4)
  names: Map<string, string>;   // the case's members by id, to name who shared a conversation
  historyNote: string | null;   // why conversations aren't saved, if they aren't
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  tokensToday: number | null;   // the user's own tokens today; null when usage isn't available
  onOpenUsage: () => void;
  admin: boolean;               // shows the administration link
  onOpenAdmin: () => void;
  cases: Case[];                // the open cases the user may see
  currentCase: Case | null;     // null: the personal space
  casesNote: string | null;     // why cases aren't available, if they aren't
  onOpenCase: (c: Case | null) => void;
  onNewCase: () => void;
  due: Case[];                  // closed cases due for deletion soon (stage 3): the user's, or all for an administrator
  showClosed: boolean;          // closed cases are listed too
  onShowClosed: (show: boolean) => void;
};

/** Library of stored documents. Clicking one adds it to the next message as an attachment. */
export function Sidebar({ documents, jobs, available, unavailableReason, inConversation, onNewChat, onUse, onDelete,
                         user, onSignOut, conversations, currentConversation, me, names, historyNote, onOpenConversation,
                         onDeleteConversation, tokensToday, onOpenUsage, admin, onOpenAdmin,
                         cases, currentCase, casesNote, onOpenCase, onNewCase, due, showClosed, onShowClosed }: Props) {
  const m = useT();
  const [confirming, setConfirming] = useState<string | null>(null);
  // The keyboard focus: on Keep (the safe choice) when a deletion is asked, back on the bin after Keep,
  // and on a document's bin while its dialog is open, so the focus returns there when it closes.
  const [back, setBack] = useState<string | null>(null);
  const keep = (id: string) => { setConfirming(null); setBack(id); };
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q ? cases.filter((c) => c.reference.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)) : cases;
  // One list for the keyboard: the personal space first, then the cases (filtered by the search).
  const entries = [{ id: MY_SPACE, textValue: m.mySpace, kase: null as Case | null },
                   ...shown.map((c) => ({ id: c.id, textValue: `${c.reference} ${c.name}`, kase: c as Case | null }))];
  return (
    <aside className="sidebar">
      <Lockup />
      <Button variant="primary" className="new-chat" onPress={onNewChat}>
        <Plus size={16} aria-hidden /> {m.newChat}
      </Button>

      <section className="library cases" aria-labelledby="cases-title">
        <h2 id="cases-title" className="label">{m.cases}</h2>
        {casesNote && <p className="caption">{casesNote}</p>}
        {due.length > 0 && (
          <div className="cases-due" role="status">
            <p className="caption"><AlertTriangle size={12} aria-hidden /> {m.casesDue(due.length)}</p>
            <ul>
              {due.map((c) => (
                <li key={c.id}>
                  <TextButton onPress={() => onOpenCase(c)}>{c.reference}</TextButton> <span>{fateLabel(c, m)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {cases.length > SEARCH_FROM && <SearchField label={m.findCase} value={query} onChange={setQuery} className="case-search" />}
        <SelectList label={m.cases} items={entries} current={currentCase?.id ?? MY_SPACE} onOpen={(e) => onOpenCase(e.kase)}
                    className="case-list">
          {(e) => e.kase === null ? (
            <span className="doc-use" title={m.mySpaceHint}>
              <User size={15} aria-hidden />
              <span className="doc-name">{m.mySpace}</span>
            </span>
          ) : (
            <span className="doc-use" title={m.openCase(e.kase.reference, e.kase.name)}>
              {e.kase.state === "closed" ? <Lock size={15} aria-hidden /> : <Folder size={15} aria-hidden />}
              <span className="doc-name">{e.kase.reference}</span>
              <span className="doc-meta">{e.kase.state === "closed" ? `${m.caseClosed} · ` : ""}{e.kase.name}</span>
            </span>
          )}
        </SelectList>
        {!casesNote && cases.length === 0 && <p className="caption">{m.casesEmpty}</p>}
        {q && shown.length === 0 && <p className="caption">{m.noCaseFound}</p>}
        {!casesNote && (
          <div className="case-tools">
            <TextButton className="new-case" onPress={onNewCase}><FolderPlus size={14} aria-hidden /> {m.newCase}</TextButton>
            <TextButton className="new-case" onPress={() => onShowClosed(!showClosed)}>
              <Lock size={14} aria-hidden /> {showClosed ? m.hideClosed : m.showClosed}
            </TextButton>
          </div>
        )}
      </section>

      <section className="library history" aria-labelledby="history-title">
        <h2 id="history-title" className="label">{m.conversations}</h2>
        {historyNote && <p className="caption">{historyNote}</p>}
        {(() => {
          // In a case: the user's own first, then what colleagues shared (read-only, no bin). Elsewhere: all theirs.
          const mine = conversations.filter((c) => !c.owner || c.owner === me);
          const shared = conversations.filter((c) => c.owner && c.owner !== me);
          const list = (items: ConversationSummary[], own: boolean) => (
            <ul>
              {items.map((c) => (
                <li key={c.id} className={`doc${c.id === currentConversation ? " doc-current" : ""}`}>
                  <Button variant="plain" className="doc-use" onPress={() => onOpenConversation(c.id)}
                          aria-current={c.id === currentConversation ? "true" : undefined}
                          title={own ? undefined : m.sharedBy(names.get(c.owner!) || c.owner!)}>
                    {own && c.shared ? <Users size={15} aria-hidden /> : <MessageSquare size={15} aria-hidden />}
                    <span className="doc-name" title={c.title}>{c.title}</span>
                    <span className="doc-meta">{own ? dayLabel(c.updated_at) : `${names.get(c.owner!) || c.owner} · ${dayLabel(c.updated_at)}`}</span>
                  </Button>
                  {own && (confirming === c.id ? (
                    <span className="doc-confirm">
                      <TextButton danger onPress={() => { setConfirming(null); onDeleteConversation(c.id); }}>{m.delete}</TextButton>
                      <TextButton autoFocus onPress={() => keep(c.id)}>{m.keep}</TextButton>
                    </span>
                  ) : (
                    <IconButton size="small" onPress={() => setConfirming(c.id)} label={m.deleteConversationLabel(c.title)} autoFocus={back === c.id}>
                      <Trash2 size={14} aria-hidden />
                    </IconButton>
                  ))}
                </li>
              ))}
            </ul>
          );
          if (shared.length === 0) return list(mine, true);
          return (
            <div className="history-lists">
              <p className="caption sublabel">{m.myConversations}</p>
              {list(mine, true)}
              <p className="caption sublabel">{m.sharedConversations}</p>
              {list(shared, false)}
            </div>
          );
        })()}
        {!historyNote && conversations.length === 0 && (
          <p className="caption">{m.conversationsEmpty}</p>
        )}
      </section>

      <section className="library documents" aria-labelledby="library-title">
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
              <Button variant="plain" className="doc-use" onPress={() => onUse(d)} isDisabled={inConversation.has(d.id)}
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
              </Button>
              {confirming === d.id ? (
                <span className="doc-confirm">
                  <TextButton danger onPress={() => { keep(d.id); onDelete(d); }}>{m.delete}</TextButton>
                  <TextButton autoFocus onPress={() => keep(d.id)}>{m.keep}</TextButton>
                </span>
              ) : (
                <IconButton size="small" onPress={() => setConfirming(d.id)} label={m.deleteDocumentLabel(d.filename)} autoFocus={back === d.id}>
                  <Trash2 size={14} aria-hidden />
                </IconButton>
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
          <TextButton onPress={onSignOut}><LogOut size={14} aria-hidden /> {m.signOut}</TextButton>
        </div>
        {tokensToday !== null && (
          <TextButton className="usage-counter" onPress={onOpenUsage} title={m.tokensTodayTitle}>
            <BarChart3 size={14} aria-hidden /> {m.tokensToday(compact(tokensToday))}
          </TextButton>
        )}
        {admin && (
          <TextButton className="usage-counter" onPress={onOpenAdmin}>
            <Shield size={14} aria-hidden /> {m.administration}
          </TextButton>
        )}
        <LanguagePicker />
        <p className="caption">{m.staysOnServer}</p>
      </div>
    </aside>
  );
}
