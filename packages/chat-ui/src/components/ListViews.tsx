/**
 * One search across every conversation, case and document the person may see (the column's Search),
 * and the origin icon the overviews share (Overviews.tsx). Opening an item takes the person to its
 * place: the conversation (in its case), the case, or the case the document is in with the document
 * ready to ask about. Nothing here decides a right: the server already filtered the lists.
 */
import { AlertTriangle, FileOutput, FileText, Folder, Lock, MessageSquare, Search } from "lucide-react";
import { useState } from "react";
import type { Case, ConversationSummary } from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { formatName } from "../lib/formats";
import type { OriginKind } from "../lib/origin";
import type { AllDocument } from "./Sidebar";
import { ViewHeader } from "./UsageView";
import { Button, SearchField } from "../ui";

/** The icon that says where a document comes from, wherever it appears (docs/design/sidebar.md §6). */
export function OriginIcon({ kind, size = 16 }: { kind: OriginKind; size?: number }) {
  return kind === "made" ? <FileOutput size={size} aria-hidden /> : kind === "pending" ? <AlertTriangle size={size} aria-hidden />
    : <FileText size={size} aria-hidden />;
}

const matches = (q: string, ...texts: (string | null | undefined)[]) =>
  !q || texts.some((t) => (t ?? "").toLowerCase().includes(q));

type Shared = { cases: Case[]; onBack: () => void };

/** One search across conversations, cases and documents. */
export function SearchView({ conversations, documents, cases, current, onOpenConversation, onOpenDocument, onOpenCase, onBack }: Shared & {
  conversations: ConversationSummary[]; documents: AllDocument[]; current: string | null;
  onOpenConversation: (c: ConversationSummary) => void; onOpenDocument: (d: AllDocument) => void; onOpenCase: (c: Case) => void;
}) {
  const m = useT();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const byId = new Map(cases.map((c) => [c.id, c]));
  const found = {
    conversations: q ? conversations.filter((c) => matches(q, c.title)) : [],
    cases: q ? cases.filter((c) => matches(q, c.reference, c.name)) : [],
    documents: q ? documents.filter((d) => matches(q, d.filename)) : [],
  };
  const none = q && found.conversations.length + found.cases.length + found.documents.length === 0;
  return (
    <section className="view">
      <ViewHeader icon={<Search size={18} aria-hidden />} title={m.search} onBack={onBack} />
      <SearchField label={m.search} placeholder={m.searchPlaceholder} value={query} onChange={setQuery} className="view-search" autoFocus />
      {none && <p className="caption">{m.searchEmpty}</p>}
      {found.cases.length > 0 && <><h2 className="label">{m.cases}</h2><ul className="item-list">
        {found.cases.map((c) => (
          <li key={c.id} className="item">
            <Button variant="plain" className="item-open" onPress={() => onOpenCase(c)} aria-current={c.id === current ? "page" : undefined}>
              {c.state === "closed" ? <Lock size={16} aria-hidden /> : <Folder size={16} aria-hidden />}
              <span className="item-name"><b>{c.reference}</b> {c.name}</span>
            </Button>
          </li>
        ))}
      </ul></>}
      {found.conversations.length > 0 && <><h2 className="label">{m.conversations}</h2><ul className="item-list">
        {found.conversations.map((c) => (
          <li key={c.id} className="item">
            <Button variant="plain" className="item-open" onPress={() => onOpenConversation(c)}>
              <MessageSquare size={16} aria-hidden />
              <span className="item-name">{c.title}</span>
              <span className="item-meta">{c.case_id && byId.get(c.case_id) ? `${byId.get(c.case_id)!.reference} · ` : ""}{dayLabel(c.updated_at)}</span>
            </Button>
          </li>
        ))}
      </ul></>}
      {found.documents.length > 0 && <><h2 className="label">{m.documents}</h2><ul className="item-list">
        {found.documents.map((d) => (
          <li key={d.id} className="item">
            <Button variant="plain" className="item-open" onPress={() => onOpenDocument(d)}>
              <FileText size={16} aria-hidden />
              <span className="item-name">{d.filename}</span>
              <span className="item-meta">{[d.case_id ? byId.get(d.case_id)?.reference : "", d.pages ? m.pages(d.pages) : formatName(d.filename)].filter(Boolean).join(" · ")}</span>
            </Button>
          </li>
        ))}
      </ul></>}
    </section>
  );
}
