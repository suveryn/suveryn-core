/**
 * The full views behind the sidebar's rows (docs/design/sidebar.md): every conversation, every case
 * and every document the person may see, each with a search box, and one search across the three.
 * Opening an item takes the person to its place: the conversation (in its case), the case, or the
 * case the document is in with the document ready to ask about. Nothing here decides a right: the
 * server already filtered the lists.
 */
import { AlertTriangle, Download, FileOutput, FileText, Filter, Folder, Link2, Loader2, Lock, MessageSquare, Pin, Search, Trash2, Users, XCircle } from "lucide-react";
import { useState } from "react";
import type { Case, ConversationSummary, Job } from "../api";
import { useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { formatName } from "../lib/formats";
import { originKind, originText, type OriginKind } from "../lib/origin";
import { caseTypeLabel } from "./CaseDialogs";
import type { AllDocument } from "./Sidebar";
import { ViewHeader } from "./UsageView";
import { Button, IconBadge, IconButton, SearchField, Select, TextButton } from "../ui";

/** The icon that says where a document comes from, wherever it appears (docs/design/sidebar.md §6). */
export function OriginIcon({ kind, size = 16 }: { kind: OriginKind; size?: number }) {
  return kind === "made" ? <FileOutput size={size} aria-hidden /> : kind === "pending" ? <AlertTriangle size={size} aria-hidden />
    : <FileText size={size} aria-hidden />;
}

const matches = (q: string, ...texts: (string | null | undefined)[]) =>
  !q || texts.some((t) => (t ?? "").toLowerCase().includes(q));

type Shared = { cases: Case[]; onBack: () => void };

export function ConversationsView({ conversations, cases, current, me, onOpen, onDelete, onBack, query: initial = "" }: Shared & {
  conversations: ConversationSummary[]; current: string; me: string;
  onOpen: (c: ConversationSummary) => void; onDelete: (c: ConversationSummary) => void; query?: string;
}) {
  const m = useT();
  const [query, setQuery] = useState(initial);
  const q = query.trim().toLowerCase();
  const byId = new Map(cases.map((c) => [c.id, c]));
  const shown = conversations.filter((c) => matches(q, c.title, byId.get(c.case_id ?? "")?.reference, byId.get(c.case_id ?? "")?.name));
  return (
    <section className="view">
      <ViewHeader icon={<MessageSquare size={18} aria-hidden />} title={m.conversations} onBack={onBack} />
      <SearchField label={m.findConversation} value={query} onChange={setQuery} className="view-search" />
      <p className="caption">{m.conversationCount(shown.length)}</p>
      <ul className="item-list">
        {shown.map((c) => {
          const k = c.case_id ? byId.get(c.case_id) : undefined;
          const own = !c.owner || c.owner === me;
          return (
            <li key={c.id} className="item">
              <Button variant="plain" className="item-open" onPress={() => onOpen(c)} aria-current={c.id === current ? "page" : undefined}>
                {k ? <IconBadge badge={<Link2 />}>{c.shared ? <Users size={16} aria-hidden /> : <MessageSquare size={16} aria-hidden />}</IconBadge>
                   : <MessageSquare size={16} aria-hidden />}
                <span className="item-name">{c.title}</span>
                <span className="item-meta">{k ? `${k.reference} · ${k.name} · ` : `${m.mySpace} · `}{dayLabel(c.updated_at)}</span>
              </Button>
              {own && <IconButton size="small" label={m.deleteConversationLabel(c.title)} onPress={() => onDelete(c)}><Trash2 size={14} aria-hidden /></IconButton>}
            </li>
          );
        })}
      </ul>
      {shown.length === 0 && <p className="caption">{q ? m.noConversationFound : m.conversationsEmpty}</p>}
    </section>
  );
}

export function DocumentsView({ documents, jobs, cases, onOpen, onDelete, onUseAsSource, onDownload, initialQuery = "", onBack }: Shared & {
  documents: AllDocument[]; onOpen: (d: AllDocument) => void; onDelete: (d: AllDocument) => void;
  /** A saved answer's Word file, built again (docs/design/sidebar.md §5). */
  onDownload?: (d: AllDocument) => void;
  /** What the search starts with: a case's reference when opened from an answer saved there. */
  initialQuery?: string;
  /** An upload that looks like sūveryn's own output: use it as a source anyway (docs/design/sidebar.md §6). */
  onUseAsSource: (d: AllDocument) => void;
  /** Uploads still being read, or failed, in the place that is open (they aren't documents yet). */
  jobs: Job[];
}) {
  const m = useT();
  const [query, setQuery] = useState(initialQuery);
  const [origin, setOrigin] = useState<"all" | "sources" | "made">("all");
  const q = query.trim().toLowerCase();
  const byId = new Map(cases.map((c) => [c.id, c]));
  const shown = documents.filter((d) => matches(q, d.filename, byId.get(d.case_id ?? "")?.reference, byId.get(d.case_id ?? "")?.name))
    .filter((d) => origin === "all" || (origin === "made") === (originKind(d) === "made"));
  return (
    <section className="view">
      <ViewHeader icon={<FileText size={18} aria-hidden />} title={m.documents} onBack={onBack} />
      <div className="view-tools">
        <SearchField label={m.findDocument} value={query} onChange={setQuery} className="view-search" />
        {/* Origin: source or made by sūveryn (docs/design/sidebar.md §6) */}
        <Select label={m.origin} icon={<Filter size={14} />} value={origin} onChange={(v) => setOrigin(v as typeof origin)}
                className={origin === "all" ? "view-filter" : "view-filter view-filter-on"}
                options={[{ id: "all", label: `${m.origin}: ${m.originFilterAll}` }, { id: "sources", label: `${m.origin}: ${m.originFilterSources}` },
                          { id: "made", label: `${m.origin}: ${m.originFilterMade}` }]} />
      </div>
      <p className="caption">{m.documentCount(shown.length)}</p>
      <ul className="item-list">
        {jobs.map((j) => (
          <li key={j.id} className="item item-static">
            <span className="item-open item-pending">
              {j.status === "failed" ? <XCircle size={16} aria-hidden /> : <Loader2 size={16} className="spin" aria-hidden />}
              <span className="item-name">{j.filename}</span>
              <span className="item-meta">{j.status === "failed" ? m.jobFailed : j.status === "queued" ? m.jobQueued : m.jobProcessing}</span>
            </span>
          </li>
        ))}
        {shown.map((d) => {
          const k = d.case_id ? byId.get(d.case_id) : undefined;
          const kind = originKind(d);
          const o = originText(d, m);
          const face = <OriginIcon kind={kind} />;
          return (
            <li key={d.id} className="item item-doc">
              <Button variant="plain" className="item-open" onPress={() => onOpen(d)} title={kind === "source" ? m.useInConversation : m.notASource}>
                {k ? <IconBadge badge={<Link2 />}>{face}</IconBadge> : face}
                <span className="item-name">{d.filename}</span>
                <span className="item-meta">{[k ? `${k.reference} · ${k.name}` : m.mySpace, d.pages ? m.pages(d.pages) : formatName(d.filename)].filter(Boolean).join(" · ")}</span>
              </Button>
              <span className="item-origin" data-kind={kind}>
                <span className="item-origin-text" title={kind === "pending" ? d.provenance?.noticed?.line : undefined}>
                  <OriginIcon kind={kind} size={14} /> <b>{o.word}</b>{kind === "pending" ? "" : ` · ${o.detail}`}
                </span>
                {kind === "pending" && <TextButton link onPress={() => onUseAsSource(d)}>{m.useAsSource}</TextButton>}
              </span>
              {d.origin === "answer" && onDownload && (
                <IconButton size="small" label={m.downloadSavedWhat(d.filename)} onPress={() => onDownload(d)}><Download size={14} aria-hidden /></IconButton>
              )}
              <IconButton size="small" label={m.deleteDocumentLabel(d.filename)} onPress={() => onDelete(d)}><Trash2 size={14} aria-hidden /></IconButton>
            </li>
          );
        })}
      </ul>
      {shown.length === 0 && <p className="caption">{q || origin !== "all" ? m.noDocumentFound : m.documentsEmpty}</p>}
      <p className="caption view-legend">{m.originLegend}</p>
    </section>
  );
}

export function CasesView({ cases, current, onOpen, onPin, onNew, onBack }: Shared & {
  current: string | null; onOpen: (c: Case) => void; onPin: (c: Case, pinned: boolean) => void; onNew: () => void;
}) {
  const m = useT();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = cases.filter((c) => matches(q, c.reference, c.name, caseTypeLabel(c.type, m)));
  const group = (state: "open" | "closed") => shown.filter((c) => c.state === state);
  const row = (c: Case) => (
    <li key={c.id} className="item">
      <Button variant="plain" className="item-open" onPress={() => onOpen(c)} aria-current={c.id === current ? "page" : undefined}
              title={m.openCase(c.reference, c.name)}>
        {c.state === "closed" ? <Lock size={16} aria-hidden /> : <Folder size={16} aria-hidden />}
        <span className="item-name"><b>{c.reference}</b> {c.name}</span>
        <span className="item-meta">{caseTypeLabel(c.type, m)}{c.state === "closed" ? ` · ${m.caseClosed}` : ""} · {dayLabel(c.updated_at)}</span>
      </Button>
      <IconButton size="small" label={c.pinned ? m.unpin : m.pin} onPress={() => onPin(c, !c.pinned)} className={c.pinned ? "item-pinned" : undefined}>
        <Pin size={14} aria-hidden />
      </IconButton>
    </li>
  );
  return (
    <section className="view">
      <ViewHeader icon={<Folder size={18} aria-hidden />} title={m.cases} onBack={onBack} />
      <div className="view-tools">
        <SearchField label={m.findCase} value={query} onChange={setQuery} className="view-search" />
        <Button size="small" onPress={onNew}>{m.newCase}</Button>
      </div>
      <p className="caption">{m.caseCount(shown.length)}</p>
      {group("open").length > 0 && <><h2 className="label">{m.openCases}</h2><ul className="item-list">{group("open").map(row)}</ul></>}
      {group("closed").length > 0 && <><h2 className="label">{m.closedCases}</h2><ul className="item-list">{group("closed").map(row)}</ul></>}
      {shown.length === 0 && <p className="caption">{q ? m.noCaseFound : m.casesEmpty}</p>}
    </section>
  );
}

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
