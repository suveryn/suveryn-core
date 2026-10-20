/**
 * The three overview pages behind the column's rows (docs/design/sidebar.md §4, artboards 06 to 08):
 * every case, every conversation and every document the person may see, as a table with a search
 * box, filter chips, a sort (or, for documents, a grouping), 25 rows per page and a menu per row. An
 * action the person has no right to is shown disabled, never hidden; the server still decides.
 *
 * Opening a row (Enter, or a click outside its own buttons) takes the person to it: the case, the
 * conversation in its case, or the case a document is in with the document ready to ask about.
 */
import {
  AlertTriangle, ArrowUpDown, Check, Clock, Download, FileOutput, Filter, Folder, Loader2, Lock, MessageSquare, MoreHorizontal,
  Pin, PinOff, Plus, ScrollText, Trash2, Upload, Users, XCircle,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { reviewPages, type CaseOverview, type ConversationSummary, type Job, type Me, type Member } from "../api";
import { locale, useT } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { ACCEPTED_FILES } from "../lib/formats";
import { originKind, originText } from "../lib/origin";
import { documentStatus, mayDeleteDocument, type DocStatus } from "../lib/overviews";
import { caseTypeLabel } from "./CaseDialogs";
import { OriginIcon } from "./ListViews";
import type { AllDocument, CaseAction } from "./Sidebar";
import {
  ActionMenu, Avatar, Button, DataTable, FileButton, FilterSelect, FilterToggle, IconBadge, Pager, PinToggle, SearchField, Select,
  TextButton, type MenuEntry, type Option, type TableColumn,
} from "../ui";

export const PAGE = 25;

const matches = (q: string, ...texts: (string | null | undefined)[]) =>
  !q || texts.some((t) => (t ?? "").toLowerCase().includes(q));
const longDate = (iso: string) => new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });
const byText = (a: string, b: string) => a.localeCompare(b, locale(), { numeric: true, sensitivity: "base" });

/** The page's head: its title, one line that sums it up, and its primary action. */
function OverviewHead({ title, summary, action }: { title: string; summary: string; action: ReactNode }) {
  return (
    <header className="overview-head">
      <div>
        <h1>{title}</h1>
        <p className="overview-summary">{summary}</p>
      </div>
      {action}
    </header>
  );
}

/** The rows of one page, and the page number kept within range when the filters shrink the list. */
function usePage<T>(rows: T[]) {
  const [page, setPage] = useState(0);
  const last = Math.max(0, Math.ceil(rows.length / PAGE) - 1);
  const at = Math.min(page, last);
  return { page: at, setPage, shown: rows.slice(at * PAGE, at * PAGE + PAGE) };
}

function Footer({ count, note, page, total, onPage }: { count: string; note?: ReactNode; page: number; total: number; onPage: (p: number) => void }) {
  const m = useT();
  return (
    <div className="overview-foot">
      <span>{count}</span>
      <span className="overview-foot-end">
        {note}
        <Pager page={page} size={PAGE} total={total} onPage={onPage}
               text={{ range: m.pageRange, previous: m.previousPage, next: m.nextPage }} />
      </span>
    </div>
  );
}

function RowMenu({ name, entries, onAction }: { name: string; entries: MenuEntry[]; onAction: (id: string) => void }) {
  const m = useT();
  return (
    <ActionMenu aria-label={m.rowActions(name)} menuLabel={m.rowActions(name)} entries={entries} onAction={onAction}
                placement="bottom end" className="overview-row-menu">
      <MoreHorizontal size={16} aria-hidden />
    </ActionMenu>
  );
}

/** "Type: all" as a chip: the filter's name, then what it is set to. */
const chip = (label: string, options: Option[]) => options.map((o) => ({ ...o, label: `${label}: ${o.label}` }));

/** A member's face, the manager with the folder badge (docs/design/sidebar.md §4). */
function Face({ member, size = "small" }: { member: Pick<Member, "user" | "name" | "username" | "avatar" | "admin" | "role">; size?: "small" }) {
  const m = useT();
  const face = <Avatar name={member.name || member.username} sub={member.user} etag={member.avatar} admin={member.admin} adminLabel={m.administrator} size={size} />;
  return member.role === "manager" ? <IconBadge badge={<Folder />} tone="neutral">{face}</IconBadge> : face;
}

// ================================================================== Cases (artboard 06)

export function CasesOverview({ cases, documents, conversations, officeWide, onOpen, onPin, onNew, onAction, onShowDocuments, onShowConversations }: {
  cases: CaseOverview[]; documents: AllDocument[]; conversations: ConversationSummary[]; officeWide: boolean;
  onOpen: (c: CaseOverview) => void; onPin: (c: CaseOverview, pinned: boolean) => void; onNew: () => void;
  onAction: (c: CaseOverview, action: CaseAction) => void;
  onShowDocuments: (caseId: string) => void; onShowConversations: (caseId: string) => void;
}) {
  const m = useT();
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [member, setMember] = useState("all");
  const [closed, setClosed] = useState(false);
  const [sort, setSort] = useState("activity");
  const q = query.trim().toLowerCase();

  const docs = new Map<string, AllDocument[]>();
  for (const d of documents) if (d.case_id) docs.set(d.case_id, [...(docs.get(d.case_id) ?? []), d]);
  const talks = new Map<string, number>();
  for (const c of conversations) if (c.case_id) talks.set(c.case_id, (talks.get(c.case_id) ?? 0) + 1);
  const people = new Map<string, string>();
  for (const c of cases) for (const x of c.members) people.set(x.user, x.name || x.username);

  const types = [...new Set(cases.map((c) => c.type))];
  const typeOptions = chip(m.filterType, [{ id: "all", label: m.filterAll }, ...types.map((t) => ({ id: t, label: caseTypeLabel(t, m) }))]);
  const memberOptions = chip(m.filterMember, [{ id: "all", label: m.everyone },
    ...[...people].sort((a, b) => byText(a[1], b[1])).map(([id, name]) => ({ id, label: name }))]);
  const sortOptions = [{ id: "activity", label: m.sortActivity }, { id: "reference", label: m.sortReference }, { id: "name", label: m.sortName }];

  const activity = (c: CaseOverview) => c.last_activity_at ?? c.updated_at;
  const rows = cases
    .filter((c) => closed || c.state === "open")
    .filter((c) => type === "all" || c.type === type)
    .filter((c) => member === "all" || c.members.some((x) => x.user === member))
    .filter((c) => matches(q, c.reference, c.name, caseTypeLabel(c.type, m)))
    .sort((a, b) => sort === "reference" ? byText(a.reference, b.reference) : sort === "name" ? byText(a.name, b.name)
      : activity(b).localeCompare(activity(a)));
  const { page, setPage, shown } = usePage(rows);
  const open = cases.filter((c) => c.state === "open").length;

  const status = (c: CaseOverview) => {
    if (c.state === "closed") {
      return <span className="overview-status overview-dim"><Lock size={14} aria-hidden />
        {c.keep || !c.keep_until ? m.statusClosedKept : m.statusClosedUntil(longDate(c.keep_until))}</span>;
    }
    const check = (docs.get(c.id) ?? []).filter((d) => d.status === "needs_review").length;
    return check
      ? <span className="overview-status" data-tone="warn"><AlertTriangle size={14} aria-hidden />{m.statusOpenReview(check)}</span>
      : <span className="overview-status"><Clock size={14} aria-hidden />{m.statusOpen}</span>;
  };
  const members = (c: CaseOverview) => {
    if (c.members.length === 0) return <span className="overview-dim">–</span>;
    const more = c.members.length - 3;
    return (
      <span className="overview-faces">
        <span className="overview-stack">{c.members.slice(0, 3).map((x) => <Face key={x.user} member={x} />)}</span>
        {more > 0 && <span className="overview-more" aria-label={m.membersCount(c.members.length)}>{m.moreMembers(more)}</span>}
        {c.access === "restricted" && c.members.length > 1 && <span className="overview-dim">{m.membersOnly}</span>}
      </span>
    );
  };
  const menu = (c: CaseOverview): MenuEntry[] => [
    { id: "open", label: m.open, icon: <Folder size={16} /> },
    { id: "pin", label: c.pinned ? m.unpin : m.pin, icon: c.pinned ? <PinOff size={16} /> : <Pin size={16} /> },
    { id: "members", label: m.members, icon: <Users size={16} />, isDisabled: c.my_role === null },
    { id: "log", label: m.accessLog, icon: <ScrollText size={16} />, isDisabled: c.my_role !== "manager" },
    "-",
    { id: "close", label: m.closeCase, icon: <Lock size={16} />, isDisabled: c.my_role !== "manager" || c.state === "closed" },
  ];

  const columns: TableColumn<CaseOverview>[] = [
    { id: "pin", label: m.colPin, hideLabel: true, width: "44px",
      render: (c) => <PinToggle label={c.pinned ? m.unpinCase(c.reference) : m.pinCase(c.reference)} isSelected={!!c.pinned} onChange={(on) => onPin(c, on)} /> },
    { id: "case", label: m.colCase, rowHeader: true,
      render: (c) => <span className="overview-name">{c.state === "closed" ? <Lock size={15} aria-hidden /> : <Folder size={15} aria-hidden />}
        <span><b>{c.reference}</b> <span className="overview-dim">{c.name}</span></span></span> },
    { id: "type", label: m.colType, render: (c) => <span className="overview-dim">{caseTypeLabel(c.type, m)}</span> },
    { id: "status", label: m.colStatus, render: status },
    { id: "members", label: m.colMembers, render: members },
    { id: "documents", label: m.colDocuments, align: "end",
      render: (c) => { const n = docs.get(c.id)?.length ?? 0; return (
        <TextButton className="overview-count" aria-label={m.documentsOfCase(c.reference, n)} onPress={() => onShowDocuments(c.id)}>{n}</TextButton>); } },
    { id: "conversations", label: m.colConversations, align: "end",
      render: (c) => { const n = talks.get(c.id) ?? 0; return (
        <TextButton className="overview-count" aria-label={m.conversationsOfCase(c.reference, n)} onPress={() => onShowConversations(c.id)}>{n}</TextButton>); } },
    { id: "activity", label: m.colActivity,
      render: (c) => { const text = [dayLabel(activity(c)), c.last_activity_by].filter(Boolean).join(" · ");
        return <span className="overview-dim overview-truncate" title={text}>{text}</span>; } },
    { id: "actions", label: m.colActions, hideLabel: true, width: "48px",
      render: (c) => <RowMenu name={`${c.reference} ${c.name}`} entries={menu(c)}
                              onAction={(id) => (id === "pin" ? onPin(c, !c.pinned) : onAction(c, id as CaseAction))} /> },
  ];

  return (
    <section className="overview">
      <OverviewHead title={m.cases} summary={m.casesSummary(open, cases.length - open, officeWide)}
                    action={<Button variant="primary" onPress={onNew}><Folder size={16} aria-hidden /> {m.newCase}</Button>} />
      <div className="overview-tools">
        <SearchField label={m.findCase} placeholder={m.caseSearchPlaceholder} value={query} onChange={setQuery} className="overview-search" />
        <FilterSelect label={m.filterType} options={typeOptions} value={type} onChange={setType} clearLabel={m.clearFilter(m.filterType)} />
        <FilterSelect label={m.filterMember} options={memberOptions} value={member} onChange={setMember} clearLabel={m.clearFilter(m.filterMember)} />
        <FilterToggle isSelected={closed} onChange={setClosed} icon={<Lock size={14} />}>{m.showClosed}</FilterToggle>
        <Select label={m.sortBy} options={sortOptions} value={sort} onChange={setSort} icon={<ArrowUpDown size={14} />} className="overview-sort" />
      </div>
      <DataTable label={m.cases} columns={columns} rows={shown} onRowAction={onOpen} empty={q || type !== "all" || member !== "all" ? m.noCaseFound : m.casesEmpty} />
      <Footer count={m.caseCount(rows.length)} note={<span>{m.casesFootnote}</span>} page={page} total={rows.length} onPage={setPage} />
    </section>
  );
}

// ================================================================== Conversations (artboard 07)

export function ConversationsOverview({ conversations, cases, me, initialCase = "all", onOpen, onDelete, onNew }: {
  conversations: ConversationSummary[]; cases: CaseOverview[]; me: Me;
  /** "all", "personal" or a case's id: filtered on a case when reached from its count or from the case. */
  initialCase?: string;
  onOpen: (c: ConversationSummary) => void; onDelete: (c: ConversationSummary) => void; onNew: () => void;
}) {
  const m = useT();
  const [query, setQuery] = useState("");
  const [where, setWhere] = useState(initialCase);
  const [from, setFrom] = useState("all");
  const [visibility, setVisibility] = useState("all");
  const [sort, setSort] = useState("activity");
  const q = query.trim().toLowerCase();
  const byId = new Map(cases.map((c) => [c.id, c]));
  const mine = (c: ConversationSummary) => !c.owner || c.owner === me.sub;

  const caseOptions = chip(m.filterCase, [{ id: "all", label: m.filterAll }, { id: "personal", label: m.personal },
    ...cases.filter((c) => conversations.some((x) => x.case_id === c.id) || c.id === initialCase)
      .sort((a, b) => byText(a.reference, b.reference)).map((c) => ({ id: c.id, label: `${c.reference} ${c.name}` }))]);
  const fromOptions = chip(m.filterFrom, [{ id: "all", label: m.everyone }, { id: "me", label: m.fromYou }, { id: "others", label: m.fromColleagues }]);
  const visOptions = chip(m.filterVisibility, [{ id: "all", label: m.filterAll }, { id: "only", label: m.visOnlyYou }, { id: "shared", label: m.visShared }]);
  const sortOptions = [{ id: "activity", label: m.sortActivity }, { id: "title", label: m.sortTitle }];

  const rows = conversations
    .filter((c) => where === "all" || (where === "personal" ? !c.case_id : c.case_id === where))
    .filter((c) => from === "all" || (from === "me") === mine(c))
    .filter((c) => visibility === "all" || (visibility === "shared") === !!c.shared)
    .filter((c) => matches(q, c.title, byId.get(c.case_id ?? "")?.reference, byId.get(c.case_id ?? "")?.name))
    .sort((a, b) => sort === "title" ? byText(a.title, b.title) : b.updated_at.localeCompare(a.updated_at));
  const { page, setPage, shown } = usePage(rows);
  const personal = conversations.filter((c) => !c.case_id).length;

  const owner = (c: ConversationSummary): Member | null => {
    if (mine(c)) return null;
    return byId.get(c.case_id ?? "")?.members.find((x) => x.user === c.owner) ?? null;
  };
  const columns: TableColumn<ConversationSummary>[] = [
    { id: "title", label: m.colConversation, rowHeader: true,
      render: (c) => <span className="overview-name">{c.shared ? <Users size={15} aria-hidden /> : <MessageSquare size={15} aria-hidden />}
        <span className="overview-strong">{c.title}</span></span> },
    { id: "case", label: m.colCase,
      render: (c) => { const k = byId.get(c.case_id ?? ""); return k
        ? <span className="overview-truncate"><b>{k.reference}</b> <span className="overview-dim">{k.name}</span></span>
        : <span className="overview-dim">{m.personal}</span>; } },
    { id: "from", label: m.colFrom,
      render: (c) => {
        const o = owner(c);
        // A colleague the case's member list doesn't name (not loaded, or no longer a member): their own
        // initials from the name the conversation carries, never the viewer's (Pod check of d1f1918).
        const face = o ? <Avatar name={o.name || o.username} sub={o.user} etag={o.avatar} admin={o.admin} adminLabel={m.administrator} size="small" />
          : mine(c) ? <Avatar name={me.name || me.username} sub={me.sub ?? ""} etag={me.avatar} admin={me.admin} adminLabel={m.administrator} size="small" />
          : <Avatar name={c.owner_name || "?"} sub={c.owner ?? ""} size="small" />;
        return (
          <span className="overview-faces">
            {c.shared ? <IconBadge badge={<MessageSquare />} tone="neutral">{face}</IconBadge> : face}
            <span>{mine(c) ? m.fromYou : c.owner_name || o?.name || ""}</span>
          </span>
        );
      } },
    { id: "visibility", label: m.colVisibility,
      render: (c) => <span className="overview-dim overview-nowrap">{!c.shared ? m.visOnlyYou : mine(c) ? m.visShared : m.visReadOnly}</span> },
    { id: "messages", label: m.colMessages, align: "end", render: (c) => c.messages ?? 0 },
    { id: "activity", label: m.colActivity, render: (c) => <span className="overview-dim">{dayLabel(c.updated_at)}</span> },
    { id: "actions", label: m.colActions, hideLabel: true, width: "48px",
      render: (c) => <RowMenu name={c.title} onAction={(id) => (id === "open" ? onOpen(c) : onDelete(c))} entries={[
        { id: "open", label: m.open, icon: <MessageSquare size={16} /> },
        "-",
        { id: "delete", label: m.delete, icon: <Trash2 size={16} />, isDisabled: !mine(c) },
      ]} /> },
  ];

  return (
    <section className="overview">
      <OverviewHead title={m.conversations} summary={m.conversationsSummary(conversations.length, personal, conversations.length - personal)}
                    action={<Button variant="primary" onPress={onNew}><Plus size={16} aria-hidden /> {m.newConversation}</Button>} />
      <div className="overview-tools">
        <SearchField label={m.findConversation} placeholder={m.conversationSearchPlaceholder} value={query} onChange={setQuery} className="overview-search" />
        <FilterSelect label={m.filterCase} options={caseOptions} value={where} onChange={setWhere} icon={<Folder size={14} />} clearLabel={m.clearFilter(m.filterCase)} />
        <FilterSelect label={m.filterFrom} options={fromOptions} value={from} onChange={setFrom} clearLabel={m.clearFilter(m.filterFrom)} />
        <FilterSelect label={m.filterVisibility} options={visOptions} value={visibility} onChange={setVisibility} clearLabel={m.clearFilter(m.filterVisibility)} />
        <Select label={m.sortBy} options={sortOptions} value={sort} onChange={setSort} icon={<ArrowUpDown size={14} />} className="overview-sort" />
      </div>
      <DataTable label={m.conversations} columns={columns} rows={shown} onRowAction={onOpen}
                 empty={q || where !== "all" || from !== "all" || visibility !== "all" ? m.noConversationFound : m.conversationsEmpty} />
      <Footer count={m.conversationCount(rows.length)} note={<span>{m.conversationsFootnote}</span>} page={page} total={rows.length} onPage={setPage} />
    </section>
  );
}

// ================================================================== Documents (artboard 08)

type DocRow = { id: string; doc?: AllDocument; job?: Job; caseId: string | null; status: DocStatus };

export function DocumentsOverview({ documents, jobs, jobsCase, cases, me, initialCase = "all", onOpen, onDelete, onUseAsSource, onDownload, onUpload }: {
  documents: AllDocument[]; cases: CaseOverview[]; me: Me;
  /** Uploads still being read, or failed, in the place that is open (`jobsCase`): not documents yet. */
  jobs: Job[]; jobsCase: string | null;
  /** "all", "personal" or a case's id. */
  initialCase?: string;
  onOpen: (d: AllDocument) => void; onDelete: (d: AllDocument) => void;
  /** An upload that looks like sūveryn's own output: use it as a source anyway (docs/design/sidebar.md §6). */
  onUseAsSource: (d: AllDocument) => void;
  /** A saved answer's Word file, built again (docs/design/sidebar.md §5). */
  onDownload: (d: AllDocument) => void;
  /** Into the place that is open, ready to ask about. */
  onUpload: (files: File[]) => void;
}) {
  const m = useT();
  const [query, setQuery] = useState("");
  const [where, setWhere] = useState(initialCase);
  const [origin, setOrigin] = useState("all");
  const [statusFilter, setStatus] = useState("all");
  const [grouped, setGrouped] = useState(false);
  const q = query.trim().toLowerCase();
  const byId = new Map(cases.map((c) => [c.id, c]));

  const statusOf = (d: AllDocument) => documentStatus(d, byId.get(d.case_id ?? ""));
  const all: DocRow[] = [
    ...jobs.filter((j) => j.status !== "ready" && j.status !== "needs_review")
      .map((j) => ({ id: `job-${j.id}`, job: j, caseId: jobsCase, status: (j.status === "failed" ? "failed" : "processing") as DocStatus })),
    ...documents.map((d) => ({ id: d.id, doc: d, caseId: d.case_id, status: statusOf(d) })),
  ];
  const name = (r: DocRow) => r.doc?.filename ?? r.job?.filename ?? "";
  const caseOptions = chip(m.filterCase, [{ id: "all", label: m.filterAll }, { id: "personal", label: m.notInCase },
    ...cases.filter((c) => documents.some((d) => d.case_id === c.id) || c.id === initialCase)
      .sort((a, b) => byText(a.reference, b.reference)).map((c) => ({ id: c.id, label: `${c.reference} ${c.name}` }))]);
  const originOptions = chip(m.colOrigin, [{ id: "all", label: m.filterAll }, { id: "sources", label: m.originFilterSources }, { id: "made", label: m.originFilterMade }]);
  const statusOptions = chip(m.filterStatus, [{ id: "all", label: m.filterAll }, { id: "ready", label: m.statusReady }, { id: "review", label: m.statusReview },
    { id: "processing", label: m.statusProcessing }, { id: "failed", label: m.statusFailed }, { id: "closed", label: m.statusCaseClosed(null) },
    { id: "notSource", label: m.statusNotASource }]);

  const caseLabel = (id: string | null) => { const k = byId.get(id ?? ""); return k ? `${k.reference} ${k.name}` : ""; };
  const rows = all
    .filter((r) => where === "all" || (where === "personal" ? !r.caseId : r.caseId === where))
    .filter((r) => origin === "all" || (r.doc ? (origin === "made") === (originKind(r.doc) === "made") : origin === "sources"))
    .filter((r) => statusFilter === "all" || r.status === statusFilter || (statusFilter === "ready" && r.status === "confirmed"))
    .filter((r) => matches(q, name(r), byId.get(r.caseId ?? "")?.reference, byId.get(r.caseId ?? "")?.name))
    .sort((a, b) => grouped ? (!a.caseId ? 1 : 0) - (!b.caseId ? 1 : 0) || byText(caseLabel(a.caseId), caseLabel(b.caseId)) : 0);
  const { page, setPage, shown } = usePage(rows);
  const inCases = new Set(documents.map((d) => d.case_id).filter(Boolean)).size;

  const addedBy = (d: AllDocument) => {
    if (!d.uploaded_by) return "";
    if (d.uploaded_by === me.sub) return me.name || me.username;
    const x = byId.get(d.case_id ?? "")?.members.find((p) => p.user === d.uploaded_by);
    return x ? x.name || x.username : "";
  };
  const status = (r: DocRow) => {
    const k = byId.get(r.caseId ?? "");
    switch (r.status) {
      case "processing": return <span className="overview-status overview-dim"><Loader2 size={14} className="spin" aria-hidden />{m.statusProcessing}</span>;
      case "failed": return <span className="overview-status" data-tone="warn"><XCircle size={14} aria-hidden />{m.statusFailed}</span>;
      case "closed": return <span className="overview-status overview-dim"><Lock size={14} aria-hidden />
        {m.statusCaseClosed(k && !k.keep && k.keep_until ? longDate(k.keep_until) : null)}</span>;
      case "notSource": return <span className="overview-status overview-dim">{m.statusNotASource}</span>;
      case "confirmed": return <span className="overview-status"><Check size={14} aria-hidden />{m.statusConfirmed}</span>;
      case "review": {
        const pages = reviewPages(r.doc?.warnings);
        return <span className="overview-status" data-tone="warn"><AlertTriangle size={14} aria-hidden />{pages.length ? m.statusReviewPages(pages.join(", ")) : m.statusReview}</span>;
      }
      default: return <span className="overview-status"><Check size={14} aria-hidden />{m.statusReady}</span>;
    }
  };
  const mayDelete = (d: AllDocument) => mayDeleteDocument(d, d.case_id ? byId.get(d.case_id) ?? null : null, me.sub ?? "");
  const menu = (d: AllDocument): MenuEntry[] => {
    const kind = originKind(d);
    const k = byId.get(d.case_id ?? "");
    return [
      { id: "open", label: m.useInConversation, icon: <MessageSquare size={16} />, isDisabled: kind !== "source" || k?.state === "closed" },
      ...(d.origin === "answer" ? [{ id: "download", label: m.downloadAsWord, icon: <Download size={16} /> }] : []),
      ...(kind === "pending" ? [{ id: "source", label: m.useAsSource, icon: <FileOutput size={16} />,
                                  isDisabled: k ? k.state === "closed" || !(k.my_role === "manager" || k.my_role === "contributor") : false }] : []),
      "-",
      { id: "delete", label: m.delete, icon: <Trash2 size={16} />, isDisabled: !mayDelete(d) },
    ];
  };
  const act = (d: AllDocument, id: string) => {
    if (id === "open") onOpen(d);
    else if (id === "download") onDownload(d);
    else if (id === "source") onUseAsSource(d);
    else if (id === "delete") onDelete(d);
  };

  const columns: TableColumn<DocRow>[] = [
    { id: "name", label: m.colName, rowHeader: true,
      render: (r) => <span className="overview-name">{r.doc ? <OriginIcon kind={originKind(r.doc)} size={15} /> : <OriginIcon kind="source" size={15} />}
        <span className="overview-strong">{name(r)}</span></span> },
    { id: "case", label: m.colCase,
      render: (r) => { const k = byId.get(r.caseId ?? ""); return k
        ? <span className="overview-truncate overview-case" title={`${k.reference} ${k.name}`}><b>{k.reference}</b> <span className="overview-dim">{k.name}</span></span>
        : <span className="overview-dim">{m.notInCase}</span>; } },
    { id: "origin", label: m.colOrigin,
      render: (r) => { if (!r.doc) return <span className="overview-dim"><b>{m.originSource}</b> · {m.originUploaded}</span>;
        const o = originText(r.doc, m);
        return <span className="overview-dim" title={originKind(r.doc) === "pending" ? r.doc.provenance?.noticed?.line : undefined}>
          <b className="overview-ink">{o.word}</b>{originKind(r.doc) === "pending" ? "" : ` · ${o.detail}`}</span>; } },
    { id: "status", label: m.colStatus, render: status },
    { id: "pages", label: m.colPages, align: "end", render: (r) => (r.doc?.pages ? r.doc.pages : <span className="overview-dim">–</span>) },
    { id: "added", label: m.colAdded,
      render: (r) => { const text = r.doc ? [dayLabel(r.doc.created_at), addedBy(r.doc)].filter(Boolean).join(" · ") : "";
        return <span className="overview-dim overview-truncate" title={text}>{text}</span>; } },
    { id: "actions", label: m.colActions, hideLabel: true, width: "48px",
      render: (r) => (r.doc ? <RowMenu name={r.doc.filename} entries={menu(r.doc)} onAction={(id) => act(r.doc!, id)} /> : null) },
  ];
  const table = (part: DocRow[], label: string) => (
    <DataTable key={label} label={label} columns={columns} rows={part}
               onRowAction={(r) => r.doc && originKind(r.doc) === "source" && byId.get(r.caseId ?? "")?.state !== "closed" && onOpen(r.doc)}
               empty={q || where !== "all" || origin !== "all" || statusFilter !== "all" ? m.noDocumentFound : m.documentsEmpty} />
  );
  const groups = grouped
    ? [...new Set(shown.map((r) => r.caseId))].map((id) => ({ id, label: id ? caseLabel(id) : m.notInCase, rows: shown.filter((r) => r.caseId === id) }))
    : [];

  return (
    <section className="overview">
      <OverviewHead title={m.documents} summary={m.documentsSummary(documents.length, inCases)}
                    action={<FileButton accept={ACCEPTED_FILES} multiple onSelect={onUpload}>
                      <Button variant="primary" title={m.uploadHint}><Upload size={16} aria-hidden /> {m.upload}</Button>
                    </FileButton>} />
      <div className="overview-tools">
        <SearchField label={m.findDocument} placeholder={m.documentSearchPlaceholder} value={query} onChange={setQuery} className="overview-search" />
        <FilterSelect label={m.filterCase} options={caseOptions} value={where} onChange={setWhere} icon={<Folder size={14} />} clearLabel={m.clearFilter(m.filterCase)} />
        <FilterSelect label={m.colOrigin} options={originOptions} value={origin} onChange={setOrigin} clearLabel={m.clearFilter(m.colOrigin)} />
        <FilterSelect label={m.filterStatus} options={statusOptions} value={statusFilter} onChange={setStatus} clearLabel={m.clearFilter(m.filterStatus)} />
        <FilterToggle isSelected={grouped} onChange={setGrouped} icon={<Filter size={14} />}>{m.groupByCase}</FilterToggle>
      </div>
      {grouped && groups.length
        ? groups.map((g) => <div key={g.id ?? "personal"} className="overview-group"><h2 className="label">{g.label}</h2>{table(g.rows, g.label)}</div>)
        : table(shown, m.documents)}
      <Footer count={m.documentCount(rows.length)} page={page} total={rows.length} onPage={setPage}
              note={<span className="overview-legend">
                <span><OriginIcon kind="source" size={14} /> <b>{m.originSource}</b> {m.legendSource}</span>
                <span><OriginIcon kind="made" size={14} /> <b>{m.originMade}</b> {m.legendMade}</span>
              </span>} />
    </section>
  );
}
