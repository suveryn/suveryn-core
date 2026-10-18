/**
 * The sidebar (docs/design/sidebar.md): one column that reads the same whatever is open.
 *
 * - The top strip: the lockup, search, and the collapse control.
 * - "New": a conversation here (or outside any case), or a new case.
 * - Three rows, Conversations, Cases and Documents, each with the most recent few under it when
 *   expanded (across every case the person may see and their own space) and an "All …" link to the
 *   full view. The row's label opens that view; the chevron expands it in place.
 * - "Pinned": the cases the person pinned, each expandable to its conversations, with an actions
 *   menu (open, unpin, members, access log, close).
 * - The account row at the bottom: a menu with usage, settings, administration, the language and
 *   sign-out.
 *
 * Collapsed, it is a 60px rail of icons that open the same views; the state is remembered in this
 * browser. Nothing here decides a right: the lists come from the server, which already filtered them.
 */
import { BarChart3, ChevronDown, ChevronsUpDown, ClipboardList, FileText, Folder, FolderPlus, Languages, Link2, Lock, LogOut, MessageSquare, MoreHorizontal, PanelLeft, Pin, Plus, Search, Settings, Shield, Users, ScrollText } from "lucide-react";
import { useState, type ReactNode } from "react";
import icon from "../brand/suveryn-icon.svg";
import type { Case, ConversationSummary, Me, StoredDocument } from "../api";
import { LANGS, lang, setLang, TABLES_FOR_TESTS as TABLES, useT, type Lang } from "../i18n";
import { dayLabel } from "../lib/conversations";
import { compact } from "../lib/usage";
import { Lockup } from "./Brand";
import { ActionMenu, Avatar, Button, Expander, IconBadge, IconButton, type MenuEntry } from "../ui";

const RECENT = 5;  // rows under an expanded section
export type SideView = "conversations" | "cases" | "documents" | "search";
export type CaseAction = "open" | "unpin" | "members" | "log" | "close";
export type AllDocument = StoredDocument & { case_id: string | null };

type Props = {
  user: Me;
  admin: boolean;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  conversations: ConversationSummary[];      // the person's own, everywhere (GET /v1/conversations?all=true)
  caseConversations: ConversationSummary[];  // the open case's, theirs and the shared ones
  documents: AllDocument[];                  // everything they may see (GET /v1/documents/all)
  cases: Case[];                             // every case they may see, open and closed
  currentCase: Case | null;
  currentConversation: string;
  casesNote: string | null;                  // why cases aren't available, if they aren't
  historyNote: string | null;
  documentsNote: string | null;
  onNewConversation: (outsideCase: boolean) => void;
  onNewCase: () => void;
  onOpenView: (view: SideView) => void;
  onOpenConversation: (c: ConversationSummary) => void;
  onOpenDocument: (d: AllDocument) => void;
  onOpenCase: (c: Case) => void;
  onCaseAction: (c: Case, action: CaseAction) => void;
  tokensToday: number | null;
  /** Administrators: how many playbooks are switched on (null: not known). */
  activePlaybooks: number | null;
  onOpenUsage: () => void;
  onOpenAdmin: (tab: "usage" | "cases" | "playbooks") => void;
  onOpenSettings: () => void;
  onOpenAvatar: () => void;
  onSignOut: () => void;
};

export function Sidebar(p: Props) {
  const m = useT();
  const [open, setOpen] = useState<Record<string, boolean>>({ conversations: true });
  const toggle = (key: string, v: boolean) => setOpen((o) => ({ ...o, [key]: v }));
  const byId = new Map(p.cases.map((c) => [c.id, c]));
  const ref = (caseId: string | null | undefined) => (caseId ? byId.get(caseId)?.reference ?? null : null);
  const openCases = p.cases.filter((c) => c.state === "open");
  const pinned = p.cases.filter((c) => c.pinned);
  const langEntries: MenuEntry[] = LANGS.map((l) => ({ id: `lang:${l}`, label: TABLES[l].languageName }));

  // ---------------------------------------------------------------- the account menu
  const accountEntries: MenuEntry[] = [
    // The order of the canvas's account menu (artboard "Accountmenu open").
    { id: "usage", label: m.myUsage, icon: <BarChart3 size={16} />, meta: p.tokensToday === null ? undefined : m.tokensToday(compact(p.tokensToday)) },
    { id: "settings", label: m.settings, icon: <Settings size={16} />, meta: m.settingsMeta },
    ...(p.admin ? [
      { id: "admin", label: m.administration, icon: <Shield size={16} />, meta: m.adminMeta, tone: "accent" as const },
      { id: "playbooks", label: m.playbooks, icon: <ClipboardList size={16} />, tone: "accent" as const,
        meta: p.activePlaybooks === null ? m.playbooksMeta : m.playbooksActive(p.activePlaybooks) },
    ] : []),
    { id: "language", label: m.language, icon: <Languages size={16} />, meta: TABLES[lang()].languageName, submenu: langEntries, selected: `lang:${lang()}` },
    "-",
    { id: "signout", label: m.signOut, icon: <LogOut size={16} /> },
  ];
  const onAccount = (id: string) => {
    if (id.startsWith("lang:")) setLang(id.slice(5) as Lang);
    else if (id === "usage") p.onOpenUsage();
    else if (id === "settings") p.onOpenSettings();
    else if (id === "admin") p.onOpenAdmin("usage");
    else if (id === "playbooks") p.onOpenAdmin("playbooks");
    else if (id === "signout") p.onSignOut();
  };
  const accountHeader = (
    <>
      <Button variant="plain" className="user-avatar" onPress={p.onOpenAvatar} aria-label={m.avatarTitle}>
        <Avatar name={p.user.name} sub={p.user.sub} etag={p.user.avatar} admin={p.user.admin} adminLabel={m.administrator} />
      </Button>
      <span className="account-who">
        <span className="account-name">{p.user.name}{p.user.admin && <span className="account-role"> · {m.administratorTitle}</span>}</span>
        <span className="account-user">{p.user.username}</span>
      </span>
    </>
  );
  const accountMenu = (trigger: ReactNode, className: string) => (
    <ActionMenu className={className} aria-label={m.accountMenu(p.user.name)} menuLabel={m.accountMenu(p.user.name)}
                entries={accountEntries} onAction={onAccount} header={accountHeader} footer={m.staysOnServer}
                placement={p.collapsed ? "right bottom" : "top start"}>
      {trigger}
    </ActionMenu>
  );

  // ---------------------------------------------------------------- "New"
  const newEntries: MenuEntry[] = [
    { id: "conversation", label: m.newConversation, icon: <MessageSquare size={16} /> },
    ...(p.currentCase ? [{ id: "outside", label: m.newConversationOutside, icon: <MessageSquare size={16} /> }] : []),
    ...(p.casesNote ? [] : [{ id: "case", label: m.newCase, icon: <FolderPlus size={16} /> }]),
  ];
  const onNew = (id: string) => {
    if (id === "conversation") p.onNewConversation(false);
    else if (id === "outside") p.onNewConversation(true);
    else if (id === "case") p.onNewCase();
  };

  // ---------------------------------------------------------------- collapsed: the rail
  if (p.collapsed) {
    return (
      <aside className="sidebar" data-collapsed aria-label={m.navigation}>
        <Button variant="plain" className="rail-mark" onPress={() => p.onCollapse(false)} aria-label={m.expandSidebar}>
          <img src={icon} width={30} height={30} alt="" />
        </Button>
        <IconButton label={m.expandSidebar} onPress={() => p.onCollapse(false)}><PanelLeft size={18} aria-hidden /></IconButton>
        <IconButton label={m.search} onPress={() => p.onOpenView("search")}><Search size={18} aria-hidden /></IconButton>
        <ActionMenu className="rail-new" aria-label={m.newMenu} menuLabel={m.newMenu} entries={newEntries} onAction={onNew} placement="right top">
          <Plus size={18} aria-hidden />
        </ActionMenu>
        <IconButton label={m.cases} onPress={() => p.onOpenView("cases")} className={p.currentCase ? "rail-current" : undefined}><Folder size={18} aria-hidden /></IconButton>
        <IconButton label={m.documents} onPress={() => p.onOpenView("documents")}><FileText size={18} aria-hidden /></IconButton>
        <IconButton label={m.conversations} onPress={() => p.onOpenView("conversations")}><MessageSquare size={18} aria-hidden /></IconButton>
        <span className="rail-space" />
        {accountMenu(<Avatar name={p.user.name} sub={p.user.sub} etag={p.user.avatar} admin={p.user.admin} adminLabel={m.administrator} />, "rail-account")}
      </aside>
    );
  }

  // ---------------------------------------------------------------- rows under a section
  const conversationRow = (c: ConversationSummary, guide = false) => {
    const r = ref(c.case_id);
    const shared = !!c.shared;
    const hint = r ? (shared ? m.inCaseShared(r) : m.inCaseOnlyYou(r)) : m.onlyYou;
    const face = shared ? <Users size={15} aria-hidden /> : <MessageSquare size={15} aria-hidden />;
    return (
      <Button key={c.id} variant="plain" className="side-sub" data-guide={guide || undefined} onPress={() => p.onOpenConversation(c)}
              aria-current={c.id === p.currentConversation ? "page" : undefined} title={guide ? undefined : hint}>
        {guide ? <span className="side-dot" aria-hidden /> : r ? <IconBadge badge={<Link2 />}>{face}</IconBadge> : face}
        <span className="side-text">{c.title}</span>
        {!guide && <span className="side-meta">{r ? `${r} · ` : ""}{dayLabel(c.updated_at)}</span>}
        {guide && (shared || (c.owner && c.owner !== p.user.sub)) && <Users size={14} className="side-shared" role="img" aria-label={m.sharedConversations} />}
      </Button>
    );
  };
  const documentRow = (d: AllDocument) => {
    const r = ref(d.case_id);
    const face = d.origin === "playbook" ? <ClipboardList size={15} aria-hidden /> : <FileText size={15} aria-hidden />;
    return (
      <Button key={d.id} variant="plain" className="side-sub" onPress={() => p.onOpenDocument(d)} title={r ? m.inCase(r) : m.notInACase}>
        {r ? <IconBadge badge={<Link2 />}>{face}</IconBadge> : face}
        <span className="side-text">{d.filename}</span>
        <span className="side-meta">{r ? `${r} · ` : ""}{m.pagesShort(d.pages)}</span>
      </Button>
    );
  };
  const caseRow = (c: Case) => (
    <Button key={c.id} variant="plain" className="side-sub" onPress={() => p.onOpenCase(c)}
            aria-current={c.id === p.currentCase?.id ? "page" : undefined} title={m.openCase(c.reference, c.name)}>
      {c.state === "closed" ? <Lock size={15} aria-hidden /> : <Folder size={15} aria-hidden />}
      <span className="side-text"><b>{c.reference}</b> <span className="side-dim">{c.name}</span></span>
    </Button>
  );
  const more = (label: string, view: SideView) => (
    <Button variant="plain" className="side-more" onPress={() => p.onOpenView(view)}>{label}</Button>
  );
  const caseActions = (c: Case): MenuEntry[] => [
    { id: "open", label: m.open, icon: <Folder size={16} /> },
    { id: "unpin", label: m.unpin, icon: <Pin size={16} /> },
    { id: "members", label: m.members, icon: <Users size={16} />, isDisabled: c.my_role === null },
    { id: "log", label: m.accessLog, icon: <ScrollText size={16} />, isDisabled: !(c.my_role === "manager" || (p.admin && c.my_role === null)) },
    { id: "close", label: m.closeCase, icon: <Lock size={16} />, isDisabled: c.my_role !== "manager" || c.state === "closed" },
  ];

  return (
    <aside className="sidebar" aria-label={m.navigation}>
      <div className="side-top">
        <Lockup />
        <IconButton size="small" label={m.search} onPress={() => p.onOpenView("search")}><Search size={16} aria-hidden /></IconButton>
        <IconButton size="small" label={m.collapseSidebar} onPress={() => p.onCollapse(true)}><PanelLeft size={16} aria-hidden /></IconButton>
      </div>

      <nav className="side-nav" aria-label={m.navigation}>
        <ActionMenu className="side-new" aria-label={m.newMenu} menuLabel={m.newMenu} entries={newEntries} onAction={onNew}>
          <Plus size={16} aria-hidden /> <span className="side-new-text">{m.newLabel}</span> <ChevronDown size={14} aria-hidden />
        </ActionMenu>

        <Expander label={m.conversations} icon={<MessageSquare size={16} />} title={m.conversationsHint} expanded={!!open.conversations}
                  onToggle={(v) => toggle("conversations", v)} onOpen={() => p.onOpenView("conversations")} toggleLabel={m.toggleRow(m.conversations)}>
          {p.historyNote && <p className="caption side-note">{p.historyNote}</p>}
          {p.conversations.slice(0, RECENT).map((c) => conversationRow(c))}
          {!p.historyNote && p.conversations.length === 0 && <p className="caption side-note">{m.conversationsEmpty}</p>}
          {p.conversations.length > 0 && more(m.allConversations, "conversations")}
        </Expander>
        <Expander label={m.cases} icon={<Folder size={16} />} meta={p.casesNote ? undefined : openCases.length} title={m.casesHint}
                  expanded={!!open.cases} onToggle={(v) => toggle("cases", v)} onOpen={() => p.onOpenView("cases")} toggleLabel={m.toggleRow(m.cases)}>
          {p.casesNote && <p className="caption side-note">{p.casesNote}</p>}
          {openCases.slice(0, RECENT).map(caseRow)}
          {!p.casesNote && openCases.length === 0 && <p className="caption side-note">{m.casesEmpty}</p>}
          {p.cases.length > 0 && more(m.allCases, "cases")}
        </Expander>
        <Expander label={m.documents} icon={<FileText size={16} />} title={m.documentsHint} expanded={!!open.documents}
                  onToggle={(v) => toggle("documents", v)} onOpen={() => p.onOpenView("documents")} toggleLabel={m.toggleRow(m.documents)}>
          {p.documentsNote && <p className="caption side-note">{p.documentsNote}</p>}
          {p.documents.slice(0, RECENT).map(documentRow)}
          {!p.documentsNote && p.documents.length === 0 && <p className="caption side-note">{m.documentsEmpty}</p>}
          {p.documents.length > 0 && more(m.allDocuments, "documents")}
        </Expander>
      </nav>

      <section className="side-pinned" aria-labelledby="pinned-title">
        <h2 id="pinned-title" className="label">{m.pinned}</h2>
        {pinned.length === 0 && !p.casesNote && <p className="caption side-note">{m.pinnedEmpty}</p>}
        {pinned.map((c) => {
          const inIt = c.id === p.currentCase?.id ? p.caseConversations : p.conversations.filter((x) => x.case_id === c.id);
          return (
            <Expander key={c.id} className="side-case" expanded={!!open[c.id]} onToggle={(v) => toggle(c.id, v)} onOpen={() => p.onOpenCase(c)}
                      current={c.id === p.currentCase?.id} toggleLabel={m.toggleRow(m.conversations)} title={m.openCase(c.reference, c.name)}
                      icon={c.state === "closed" ? <Lock size={16} /> : <Folder size={16} />}
                      label={<><b>{c.reference}</b> <span className="side-dim">{c.state === "closed" ? `${m.caseClosed} · ` : ""}{c.name}</span></>}
                      actions={
                        <ActionMenu className="side-actions" aria-label={m.caseActions(c.reference)} menuLabel={m.caseActions(c.reference)}
                                    entries={caseActions(c)} onAction={(a) => p.onCaseAction(c, a as CaseAction)} placement="bottom end">
                          <MoreHorizontal size={16} aria-hidden />
                        </ActionMenu>
                      }>
              {inIt.map((x) => conversationRow(x, true))}
              {inIt.length === 0 && <p className="caption side-note">{m.caseConversationsEmpty}</p>}
            </Expander>
          );
        })}
      </section>

      <span className="side-space" />
      {accountMenu(
        <>
          <Avatar name={p.user.name} sub={p.user.sub} etag={p.user.avatar} admin={p.user.admin} adminLabel={m.administrator} />
          <span className="account-row-name">{p.user.name}</span>
          <ChevronsUpDown size={14} aria-hidden />
        </>, "account-row")}
    </aside>
  );
}
