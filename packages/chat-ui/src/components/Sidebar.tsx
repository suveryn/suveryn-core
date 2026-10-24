/**
 * The left column (docs/design/sidebar.md §2): one column that reads the same whatever is open.
 *
 * - The top strip: the lockup, search, and the collapse control (on a narrow screen, in the drawer: close).
 * - "New": a personal chat, outside any case, or a new case.
 * - Three navigation rows, Conversations, Cases (with the count of open cases) and Documents: each
 *   opens its overview in the main area; they don't expand.
 * - "Pinned": the cases the person pinned, then their pinned personal conversations. The chevron on
 *   the left opens a case in place, its conversations on a hairline (an orange dot for the open one);
 *   a pinned conversation has its icon and no chevron. A three-dot menu per row.
 * - "Recent": the person's conversations, newest first, across cases and their own space; the icon
 *   says who sees it, the case's reference is the meta; a three-dot menu per row (Pin, Rename, Move to
 *   a case, Delete). Never one already shown under Pinned.
 * - First use: one line instead of Pinned and Recent.
 * - The account row at the bottom: usage, settings, language, the administrators' items under their
 *   own label, sign-out.
 *
 * Collapsed, it is a 60px rail of icons in the same order; the state is remembered in this browser.
 * Nothing here decides a right: the lists come from the server, which already filtered them.
 */
import { listedTitle } from "../lib/conversations";
import { PIN_HINT_AFTER, pinnedConversations, type ConversationAction } from "../lib/conversationActions";
import { conversationMenu } from "./ConversationDialogs";
import { BarChart3, ChevronDown, ChevronsUpDown, ClipboardList, Clock, FileText, Folder, FolderKey, FolderOpen, FolderPlus, Languages, Lock, LogOut, MessageSquare, MessageSquareLock, MessagesSquare, MoreHorizontal, PanelLeft, Pin, PinOff, Plus, Search, Settings, Shield, Users, ScrollText, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import icon from "../brand/suveryn-icon.svg";
import type { Case, ConversationSummary, Me, StoredDocument } from "../api";
import { LANGS, LANGUAGE_NAMES, lang, setLang, useT, type Lang } from "../i18n";
import { compact } from "../lib/usage";
import { Lockup } from "./Brand";
import { ActionMenu, Avatar, Button, Expander, IconButton, type MenuEntry } from "../ui";

const RECENT = 8;  // conversations under Recent
export type SideView = "conversations" | "cases" | "documents" | "search";
export type CaseAction = "open" | "unpin" | "members" | "log" | "close";
export type AllDocument = StoredDocument & { case_id: string | null };

type Props = {
  user: Me;
  /** The overview open in the main area, if any: its navigation row is current. */
  view: string;
  /** In the drawer on a narrow screen: a close button instead of collapsing (docs/design/sidebar.md §2). */
  onClose?: () => void;
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
  onConversationAction: (c: ConversationSummary, action: ConversationAction) => void;
  /** Show once, under Pinned, that a case keeps conversations together (more than five pinned, §3). */
  pinHint: boolean;
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
  const pinnedOwn = pinnedConversations(p.conversations);
  const langEntries: MenuEntry[] = LANGS.map((l) => ({ id: `lang:${l}`, label: LANGUAGE_NAMES[l] }));

  // ---------------------------------------------------------------- the account menu
  // The order of §2 and artboard 04: usage, settings, language; the administrators' items under their
  // own label; sign out.
  const accountEntries: MenuEntry[] = [
    { id: "usage", label: m.myUsage, icon: <BarChart3 size={16} />, meta: p.tokensToday === null ? undefined : m.tokensToday(compact(p.tokensToday)) },
    { id: "settings", label: m.settings, icon: <Settings size={16} />, meta: m.settingsMeta },
    { id: "language", label: m.language, icon: <Languages size={16} />, meta: LANGUAGE_NAMES[lang()], submenu: langEntries, selected: `lang:${lang()}` },
    ...(p.admin ? [{ heading: m.administratorsOnly, items: [
      { id: "admin", label: m.administration, icon: <Shield size={16} />, meta: m.adminMeta },
      { id: "playbooks", label: m.playbooks, icon: <ClipboardList size={16} />,
        meta: p.activePlaybooks === null ? m.playbooksMeta : m.playbooksActive(p.activePlaybooks) },
    ] }] : []),
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
  // A personal chat, outside any case (it says so when a case is open), and a case (§2, artboard 05). In an
  // open case its contributors also get a conversation in it, first: the only way to start one there
  // without leaving the case and opening it again (Pod check of 470b9da).
  const inCase = p.currentCase && p.currentCase.state !== "closed"
    && (p.currentCase.my_role === "contributor" || p.currentCase.my_role === "manager") ? p.currentCase : null;
  const newEntries: MenuEntry[] = [
    ...(inCase ? [{ id: "in-case", label: m.newConversationInCase(inCase.reference), icon: <MessagesSquare size={16} />,
                    description: m.newConversationInCaseHint }] : []),
    { id: "conversation", label: m.newConversation, icon: <MessageSquare size={16} />,
      description: p.currentCase ? m.newChatHintInCase(p.currentCase.reference) : m.newChatHint },
    ...(p.casesNote ? [] : [{ id: "case", label: m.newCase, icon: <FolderPlus size={16} />, description: m.newCaseHint }]),
  ];
  const onNew = (id: string) => {
    if (id === "conversation") p.onNewConversation(true);
    else if (id === "in-case") p.onNewConversation(false);
    else if (id === "case") p.onNewCase();
  };

  // ---------------------------------------------------------------- collapsed: the rail
  if (p.collapsed) {
    return (
      <aside className="sidebar" data-collapsed aria-label={m.navigation}>
        <Button variant="plain" className="rail-mark" onPress={() => p.onCollapse(false)} aria-label={m.expandSidebar} title={m.expandSidebar}>
          <img src={icon} width={30} height={30} alt="" />
        </Button>
        <IconButton label={m.search} onPress={() => p.onOpenView("search")}><Search size={18} aria-hidden /></IconButton>
        <ActionMenu className="rail-new" aria-label={m.newMenu} menuLabel={m.newMenu} entries={newEntries} onAction={onNew} placement="right top">
          <Plus size={18} aria-hidden />
        </ActionMenu>
        {/* the navigation rows, in their order everywhere (§2) */}
        <IconButton label={m.conversations} onPress={() => p.onOpenView("conversations")} className={p.view === "conversations" ? "rail-current" : undefined}><MessageSquare size={18} aria-hidden /></IconButton>
        <IconButton label={m.cases} onPress={() => p.onOpenView("cases")} className={p.view === "cases" ? "rail-current" : undefined}><Folder size={18} aria-hidden /></IconButton>
        <IconButton label={m.documents} onPress={() => p.onOpenView("documents")} className={p.view === "documents" ? "rail-current" : undefined}><FileText size={18} aria-hidden /></IconButton>
        <span className="rail-space" />
        {accountMenu(<Avatar name={p.user.name} sub={p.user.sub} etag={p.user.avatar} admin={p.user.admin} adminLabel={m.administrator} />, "rail-account")}
      </aside>
    );
  }

  // ---------------------------------------------------------------- a conversation row
  // In Recent: the icon says who sees it, the case's reference is the meta. Under a pinned case: on
  // the hairline, an orange dot for the open one.
  const conversationRow = (c: ConversationSummary, underCase = false, pinnedRow = false) => {
    const r = ref(c.case_id);
    const shared = !!c.shared || (!!c.owner && c.owner !== p.user.sub);
    const hint = r ? (shared ? m.inCaseShared(r) : m.inCaseOnlyYou(r)) : m.onlyYou;
    const current = c.id === p.currentConversation;
    const row = (
      <Button key={c.id} variant="plain" className={underCase ? "side-sub" : "side-recent"} data-guide={underCase || undefined}
              onPress={() => p.onOpenConversation(c)} aria-current={current ? "page" : undefined} title={hint}>
        {underCase
          ? <span className="side-dot" data-current={current || undefined} aria-hidden />
          : c.shielded ? <MessageSquareLock size={14} aria-hidden /> : shared ? <Users size={14} aria-hidden /> : <MessageSquare size={14} aria-hidden />}
        {/* §11: a strictly confidential case's conversation, without its title */}
        <span className="side-text" data-shielded={c.shielded || undefined}
              aria-label={c.shielded && r ? m.shieldedIn(r) : undefined}>{listedTitle(c)}</span>
        {underCase ? (shared && <Users size={13} className="side-shared" role="img" aria-label={m.sharedConversations} />)
                   : r && <span className="side-meta">{r}</span>}
      </Button>
    );
    if (underCase) return row;
    // Recent and a pinned conversation: the row and its three-dot menu (§2)
    const title = listedTitle(c);
    return (
      <div key={c.id} className="side-item" data-pinned={pinnedRow || undefined}>
        {row}
        <ActionMenu className="side-actions" aria-label={m.conversationMenu(title)} menuLabel={m.conversationMenu(title)}
                    entries={conversationMenu(c, p.user.sub, m)} onAction={(a) => p.onConversationAction(c, a as ConversationAction)}
                    placement="bottom end">
          <MoreHorizontal size={16} aria-hidden />
        </ActionMenu>
      </div>
    );
  };
  const caseActions = (c: Case): MenuEntry[] => [
    { id: "open", label: m.open, icon: <Folder size={16} /> },
    { id: "unpin", label: m.unpin, icon: <PinOff size={16} /> },
    { id: "members", label: m.members, icon: <Users size={16} />, isDisabled: c.my_role === null },
    { id: "log", label: m.accessLog, icon: <ScrollText size={16} />, isDisabled: !(c.my_role === "manager" || (p.admin && c.my_role === null)) },
    "-",
    { id: "close", label: m.closeCase, icon: <Lock size={16} />, isDisabled: c.my_role !== "manager" || c.state === "closed" },
  ];
  const navRow = (view: SideView, label: string, icon: ReactNode, meta?: number) => (
    <Button variant="plain" className="side-row" onPress={() => p.onOpenView(view)} aria-current={p.view === view ? "page" : undefined}>
      <span className="side-row-icon" aria-hidden>{icon}</span>
      <span className="side-text">{label}</span>
      {meta !== undefined && <span className="side-meta">{meta}</span>}
    </Button>
  );

  // Recent never repeats what Pinned shows: the conversations of a pinned case that is open in the column.
  const shownUnderPinned = new Set(pinned.filter((c) => open[c.id]).flatMap((c) =>
    (c.id === p.currentCase?.id ? p.caseConversations : p.conversations.filter((x) => x.case_id === c.id)).map((x) => x.id)));
  for (const c of pinnedOwn) shownUnderPinned.add(c.id);
  const recent = p.conversations.filter((c) => !shownUnderPinned.has(c.id)).slice(0, RECENT);
  const firstUse = pinned.length === 0 && pinnedOwn.length === 0 && p.conversations.length === 0 && !p.historyNote;
  const notes = [p.casesNote, p.documentsNote].filter(Boolean) as string[];

  return (
    <aside className="sidebar" aria-label={m.navigation}>
      <div className="side-top">
        <Lockup />
        <IconButton size="small" label={m.search} onPress={() => p.onOpenView("search")}><Search size={16} aria-hidden /></IconButton>
        {p.onClose
          ? <IconButton size="small" label={m.closeMenu} onPress={p.onClose}><X size={16} aria-hidden /></IconButton>
          : <IconButton size="small" label={m.collapseSidebar} onPress={() => p.onCollapse(true)}><PanelLeft size={16} aria-hidden /></IconButton>}
      </div>

      <nav className="side-nav" aria-label={m.navigation}>
        <ActionMenu className="side-new" aria-label={m.newMenu} menuLabel={m.newMenu} entries={newEntries} onAction={onNew}>
          <Plus size={16} aria-hidden /> <span className="side-new-text">{m.newLabel}</span> <ChevronDown size={14} aria-hidden />
        </ActionMenu>
        {navRow("conversations", m.conversations, <MessageSquare size={16} />)}
        {navRow("cases", m.cases, <Folder size={16} />, p.casesNote ? undefined : openCases.length)}
        {navRow("documents", m.documents, <FileText size={16} />)}
        {notes.map((n) => <p key={n} className="caption side-note">{n}</p>)}
      </nav>

      {firstUse && <p className="caption side-note side-first">{m.firstUseColumn}</p>}

      {(pinned.length > 0 || pinnedOwn.length > 0) && (
        <section className="side-section" aria-labelledby="pinned-title">
          <h2 id="pinned-title" className="label side-label"><Pin size={12} aria-hidden /> {m.pinned}</h2>
          {pinned.map((c) => {
            const inIt = c.id === p.currentCase?.id ? p.caseConversations : p.conversations.filter((x) => x.case_id === c.id);
            const expanded = !!open[c.id];
            return (
              <Expander key={c.id} className="side-case" toggleFirst expanded={expanded} onToggle={(v) => toggle(c.id, v)}
                        onOpen={() => p.onOpenCase(c)} current={c.id === p.currentCase?.id}
                        toggleLabel={m.caseConversationsToggle(c.reference)} title={m.openCase(c.reference, c.name)}
                        icon={c.state === "closed" ? <Lock size={16} /> : c.confidential ? <FolderKey size={16} /> : expanded ? <FolderOpen size={16} /> : <Folder size={16} />}
                        label={<><b>{c.reference}</b> <span className="side-dim">{c.state === "closed" ? `${m.caseClosed} · ` : ""}{c.name}</span></>}
                        actions={
                          <ActionMenu className="side-actions" aria-label={m.caseActions(c.reference)} menuLabel={m.caseActions(c.reference)}
                                      entries={caseActions(c)} onAction={(a) => p.onCaseAction(c, a as CaseAction)} placement="bottom end">
                            <MoreHorizontal size={16} aria-hidden />
                          </ActionMenu>
                        }>
                <div className="side-guide">
                  {inIt.map((x) => conversationRow(x, true))}
                  {inIt.length === 0 && <p className="caption side-note">{m.caseConversationsEmpty}</p>}
                </div>
              </Expander>
            );
          })}
          {pinnedOwn.map((c) => conversationRow(c, false, true))}
          {p.pinHint && pinnedOwn.length > PIN_HINT_AFTER && <p className="caption side-note side-pin-hint" role="status">{m.fivePinned}</p>}
        </section>
      )}

      {(recent.length > 0 || p.historyNote) && (
        <section className="side-section" aria-labelledby="recent-title">
          <h2 id="recent-title" className="label side-label"><Clock size={12} aria-hidden /> {m.recent}</h2>
          {p.historyNote && <p className="caption side-note">{p.historyNote}</p>}
          {recent.map((c) => conversationRow(c))}
        </section>
      )}

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
