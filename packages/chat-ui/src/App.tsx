/**
 * The chat application: owns all state and talks to the gateway (src/api.ts).
 *
 * - Nothing is shown before sign-in (App → SignIn); once signed in, Chat mounts.
 * - Server state (health, stored documents, upload jobs) is polled; uploads are tracked per
 *   attachment until their job is ready.
 * - Conversations are saved on the server, per user (suveryn-tracker#5): after each answer the
 *   whole conversation is saved, and the sidebar lists earlier ones to open again. Nothing is
 *   written to browser storage. Signing out asks whether to keep the history (the default) or
 *   delete it. Without a database on the server, the conversation lives only in memory.
 * - Cases (suveryn-tracker#10): the sidebar opens a case or the personal space; documents,
 *   uploads, conversations and questions are then that case's (the gateway checks the right),
 *   and switching starts a new chat there. The personal space is the user's own, as before cases.
 * - The sidebar (docs/design/sidebar.md) lists conversations, cases and documents across every
 *   place at once; opening one of them goes to its place first. Pinned cases are the user's own
 *   choice (per user, on the server). The sidebar collapses to a rail, remembered in this browser.
 * - Each question is sent with the completed earlier turns (lib/history.ts) and every document
 *   used so far in the conversation that still exists.
 * - Answers stream in as deltas; on an error event the partial text is discarded (the gateway's
 *   contract) and the turn shows an error instead.
 */
import { AlertCircle, FileText, Folder, FolderPlus, Lock, LogIn, Menu, MessageSquare, MoreHorizontal, ScrollText, Share2, Trash2, Users, UsersRound } from "lucide-react";
import icon from "./brand/suveryn-icon.svg";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDocument, documentConversations, getHealth, getJob, listDocuments, reviewPages, streamChat, uploadDocument,
  getMe, listModels, onSignedOut, signIn, signOut, type Health, type Job, type Me, type ModelInfo, type StoredDocument,
  type WireMessage, type Citation, type ConversationSummary, listConversations, getConversation, saveConversation, deleteConversation,
  deleteAllConversations, getMyUsage, listCases, listCasesOverview, deleteCase, getCase, closeCase, type Case, type CaseOverview, type Member,
  listMembers, shareConversation, confirmAsSource, saveAnswerToCase, documentContent, listAllConversations, listAllDocuments, pinCase, casePlaybooks, type PlaybookInfo, listAdminPlaybooks,
} from "./api";
import { Lockup } from "./components/Brand";
import { caseTypeLabel, CloseCaseDialog, DeleteCaseDialog, NewCaseDialog } from "./components/CaseDialogs";
import { AccessLogDialog, CaseFaces, MembersDialog, roleLabel } from "./components/CaseMembers";
import { AvatarDialog } from "./components/AvatarDialog";
import { OfflineBar } from "./components/OfflineBar";
import { CaseState } from "./components/CaseState";
import { PlaybookView } from "./components/DeedIntake";
import { Composer } from "./components/Composer";
import { DeleteDocumentDialog } from "./components/DeleteDocumentDialog";
import { AssistantMessage, SourcePanel, UserMessage, type OpenSource, type SaveToCase } from "./components/Messages";
import { answerFileName, savedAnswer, savedWord, searchText } from "./lib/saved";
import { LanguagePicker } from "./components/LanguagePicker";
import { SearchView } from "./components/ListViews";
import { CasesOverview, ConversationsOverview, DocumentsOverview } from "./components/Overviews";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar, type AllDocument, type CaseAction, type SideView } from "./components/Sidebar";
import { SignOutDialog } from "./components/SignOutDialog";
import { AdminView, UsageView, type AdminTab } from "./components/UsageView";
import { today } from "./lib/usage";
import { conversationTitle, fromSaved, MAX_SAVED_TURNS, newConversationId, toSaved, usesDocument, withoutDocument } from "./lib/conversations";
import { conversationHistory } from "./lib/history";
import { originKind } from "./lib/origin";
import { claimRedirect, clearRedirect } from "./lib/signin";
import { lang, locale, useT } from "./i18n";
import { ActionMenu, Button, Drawer, I18nProvider, IconButton, InlineNotice, NARROW, useMedia } from "./ui";
import { isReady, staysInComposer, type AssistantTurn, type Attachment, type Turn, type UserTurn } from "./types";

const TAGLINE = "AI for work that can't leave the premises"; // English in every language, as on the website
const SIDEBAR_KEY = "suveryn.sidebar";  // "collapsed" when the rail is chosen (this browser only)
const readCollapsed = () => { try { return localStorage.getItem(SIDEBAR_KEY) === "collapsed"; } catch { return false; } };
let counter = 0;
// Unique across page loads too: turns of a reopened conversation keep the ids they were saved with.
/** An attachment as its upload job says it is now. An upload that carries sūveryn's own export mark is
 *  read but waits for the person's choice before it is a source (docs/design/sidebar.md §6): never
 *  blocked, never used unasked. */
function attachmentFromJob(a: Attachment, j: Job): Attachment {
  const noticed = j.noticed && (j.status === "ready" || j.status === "needs_review") ? j.noticed : undefined;
  return { ...a, status: noticed ? "noticed" : j.status, noticed, documentId: j.document_id ?? undefined,
           error: j.error ?? undefined, reviewPages: reviewPages(j.warnings), pages: j.pages ?? undefined };
}
const nextId = () => `t${Date.now().toString(36)}-${++counter}`;
const HEALTH_EVERY = 10_000;

/**
 * Sign-in gate. Signed out on arrival (first visit, after signing out): straight to Keycloak's
 * login page, in the interface language (lib/signin.ts). The sign-in screen shows only when a
 * session ends while working (any API call answering 401), when sign-in is unavailable, or when a
 * sign-in didn't complete. The chat itself only mounts when signed in.
 */
export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined: still checking
  const [ended, setEnded] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [stuck, setStuck] = useState(false); // came back signed out right after a redirect

  useEffect(() => {
    onSignedOut(() => { setEnded(true); setMe(null); });
    getMe().then((user) => {
      if (user) { clearRedirect(); setMe(user); return; }
      const step = claimRedirect();
      if (step === "go") signIn();
      else if (step === "stuck") { setStuck(true); setMe(null); } // "started": already leaving, render nothing
    }).catch((e: Error) => { setUnavailable(e.message); setMe(null); });
  }, []);

  useT(); // re-render on a language change, so React Aria's numbers and dates follow it
  if (me === undefined) return null; // checking, or on the way to the login page
  return (
    <I18nProvider locale={locale()}>
      {me === null ? <SignIn ended={ended} unavailable={unavailable} stuck={stuck} /> : <Chat me={me} />}
    </I18nProvider>
  );
}

function SignIn({ ended, unavailable, stuck }: { ended: boolean; unavailable: string | null; stuck: boolean }) {
  const m = useT();
  return (
    <main className="signin">
      <Lockup />
      <h1>{TAGLINE}</h1>
      {ended && <InlineNotice icon={<AlertCircle size={14} />}>{m.sessionEnded}</InlineNotice>}
      {stuck && !ended && <InlineNotice icon={<AlertCircle size={14} />}>{m.signInIncomplete}</InlineNotice>}
      {unavailable
        ? <InlineNotice icon={<AlertCircle size={14} />} tone="error">{m.signInUnavailable(unavailable)}</InlineNotice>
        : <Button variant="primary" onPress={signIn}><LogIn size={16} aria-hidden /> {m.signIn}</Button>}
      <p className="caption">{m.signInCaption}</p>
      <LanguagePicker />
    </main>
  );
}

function Chat({ me }: { me: Me }) {
  const m = useT();
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [chosenModel, setChosenModel] = useState<string | null>(null); // null: the appliance default
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState<Attachment[]>([]); // attachments for the next message
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState(newConversationId);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [askingSignOut, setAskingSignOut] = useState(false);
  const [view, setView] = useState<"chat" | "usage" | "admin" | "playbook" | SideView>("chat");
  const narrow = useMedia(NARROW);
  const [drawer, setDrawer] = useState(false);
  // The Conversations and Documents overviews' case filter: "all" from the column, a case's id from
  // its count in the Cases overview, from the case itself or from an answer saved there (docs/design/sidebar.md §4).
  const [overviewFilter, setOverviewFilter] = useState("all");
  const [overviewCases, setOverviewCases] = useState<CaseOverview[] | null>(null);
  const [savedHere, setSavedHere] = useState<Set<string>>(new Set());  // answers saved during this visit: Undo is offered
  useEffect(() => { if (view !== "documents" && view !== "conversations") setOverviewFilter("all"); }, [view]);
  const showOverview = (v: "documents" | "conversations", filter = "all") => { setOverviewFilter(filter); setView(v); };
  const [adminTab, setAdminTab] = useState<AdminTab>("usage");
  const [collapsed, setCollapsedState] = useState(readCollapsed);
  const setCollapsed = (c: boolean) => { setCollapsedState(c); try { localStorage.setItem(SIDEBAR_KEY, c ? "collapsed" : "expanded"); } catch { /* this page only */ } };
  const [showSettings, setShowSettings] = useState(false);
  const [allConversations, setAllConversations] = useState<ConversationSummary[]>([]);  // the user's own, everywhere
  const [allDocuments, setAllDocuments] = useState<AllDocument[]>([]);                 // everything they may see
  const [playbooks, setPlaybooks] = useState<PlaybookInfo[]>([]);                      // the open case's
  const [activePlaybooks, setActivePlaybooks] = useState<number | null>(null);         // administrators: how many are on
  const [tokensToday, setTokensToday] = useState<number | null>(null); // null: usage not available
  const [cases, setCases] = useState<Case[]>([]);
  const [currentCase, setCurrentCase] = useState<Case | null>(null); // null: the personal space
  const [newCase, setNewCase] = useState(false);
  const [deletingCase, setDeletingCase] = useState(false);
  const [closingCase, setClosingCase] = useState(false);
  const [showMembers, setShowMembers] = useState(false);
  const [showAvatar, setShowAvatar] = useState(false);
  const [avatar, setAvatar] = useState<string | null>(me.avatar ?? null);  // the picture's ETag; null: initials
  const self: Me = { ...me, avatar };
  const [showLog, setShowLog] = useState(false);
  const [caseMembers, setCaseMembers] = useState<Member[]>([]);  // the open case's members (stage 4), for its header
  const names = useMemo(() => new Map(caseMembers.map((x) => [x.user, x.name || x.username])), [caseMembers]);
  // The source open in the panel beside the conversation (docs/design/sidebar.md §5): which answer, which source.
  const [source, setSource] = useState<(OpenSource & { turnId: string }) | null>(null);
  const caseId = currentCase?.id ?? null;
  const openCaseId = useRef(caseId);
  openCaseId.current = caseId;
  // What the signed-in user is in the open case: a member's role, "reader" for a colleague in an
  // office-wide appliance, or null for an administrator who only sees the case exists.
  const role = currentCase?.my_role ?? null;
  const closed = currentCase?.state === "closed";
  // The open conversation as the sidebar lists it: someone else's shared one is read-only (stage 4).
  const current = conversations.find((c) => c.id === conversationId);
  const readOnly = !!current && !!current.owner && current.owner !== (me.sub ?? "");
  const canShare = !!currentCase && !closed && !readOnly && (role === "contributor" || role === "manager") && turns.length > 0;
  const manages = role === "manager";
  const contributes = role === "contributor" || role === "manager";
  const administers = currentCase !== null && role === null && (me.admin ?? false);
  const lastSaved = useRef(""); // the turns as last saved (or opened), so unchanged turns aren't saved again
  const abort = useRef<AbortController | null>(null);
  const stopped = useRef(false);  // the person pressed Stop: the abort keeps what was written
  const endRef = useRef<HTMLDivElement>(null);

  const documentsReady = health?.documents.status === "ready";
  const historyReady = health?.history?.status === "ready";
  const casesReady = health?.cases?.status === "ready";

  // ---------------------------------------------------------------- server state
  const refreshDocuments = useCallback(async () => {
    try {
      const r = await listDocuments(caseId);
      setDocuments(r.documents);
      setJobs(r.jobs);
    } catch { /* document handling unavailable; the health check explains why */ }
  }, [caseId]);

  // The server's health, every HEALTH_EVERY ms; *Try now* (the server-unreachable bar) checks at once.
  // ``reachable`` is false only after a check found nothing: not while the first one runs.
  const [checks, setChecks] = useState(0);
  const [reachable, setReachable] = useState(true);
  const [nextCheck, setNextCheck] = useState(0);
  const checkNow = () => setChecks((c) => c + 1);
  useEffect(() => {
    let alive = true;
    (async () => {
      const h = await getHealth();
      if (!alive) return;
      setHealth(h);
      setReachable(h !== null);
      try { const m = await listModels(); if (alive) setModels(m); } catch { /* the health check explains why */ }
    })();
    setNextCheck(Date.now() + HEALTH_EVERY);
    const t = setTimeout(checkNow, HEALTH_EVERY);
    return () => { alive = false; clearTimeout(t); };
  }, [checks]);

  useEffect(() => { if (documentsReady && !administers) refreshDocuments(); }, [documentsReady, refreshDocuments, administers]);

  const refreshConversations = useCallback(async () => {
    try { setConversations(await listConversations(caseId)); } catch { /* the health check explains why */ }
    try { setAllConversations(await listAllConversations()); } catch { /* same */ }
  }, [caseId]);
  useEffect(() => { if (historyReady && !administers) refreshConversations(); }, [historyReady, refreshConversations, administers]);
  useEffect(() => { if (documentsReady) listAllDocuments().then(setAllDocuments).catch(() => {}); }, [documentsReady, documents, caseId]);

  // Every case the user may see, open and closed: the sidebar's rows and its pinned cases.
  const refreshCases = useCallback(async () => {
    try { setCases(await listCases(true)); } catch { /* the health check explains why */ }
  }, []);
  useEffect(() => { if (casesReady) refreshCases(); }, [casesReady, refreshCases]);
  // The overviews' cases, with their members and last activity: read again whenever one is opened
  // and when the cases change. Until then (or if it fails) the plain list, without members.
  const inOverview = view === "cases" || view === "conversations" || view === "documents";
  useEffect(() => {
    if (!casesReady || !inOverview) return;
    listCasesOverview().then(setOverviewCases).catch(() => setOverviewCases(null));
  }, [casesReady, inOverview, cases]);

  // Administrators: the account menu says how many playbooks are on (read again on returning to the chat).
  useEffect(() => {
    if (!me.admin || view !== "chat") return;
    listAdminPlaybooks().then((ps) => setActivePlaybooks(ps.filter((x) => x.active !== false).length)).catch(() => setActivePlaybooks(null));
  }, [me.admin, view]);

  // The open case's playbooks (docs/design/playbooks.md): the composer's chip; none in the personal
  // space. Read again on returning to the chat: an administrator may just have switched one off.
  useEffect(() => {
    if (view !== "chat") return;
    if (!caseId || role === null) { setPlaybooks([]); return; }
    casePlaybooks(caseId).then(setPlaybooks).catch(() => setPlaybooks([]));
  }, [caseId, role, view]);

  // The sidebar's usage counter: today's own tokens, refreshed after each answer.
  useEffect(() => {
    if (busy) return;
    getMyUsage(today(new Date()).start).then((r) => setTokensToday(r.totals.total_tokens)).catch(() => setTokensToday(null));
  }, [busy]);

  // Save the conversation whenever it changed and no answer is streaming.
  useEffect(() => {
    if (!historyReady || busy || turns.length === 0 || readOnly) return;  // someone else's shared conversation is never saved over
    const saved = toSaved(turns);
    const body = JSON.stringify(saved);
    if (body === lastSaved.current) return;
    lastSaved.current = body;
    if (saved.length > MAX_SAVED_TURNS) { setProblem(m.saveFailed(m.conversationTooLong)); return; }  // the server refuses it
    saveConversation(conversationId, conversationTitle(turns), saved, caseId)
      .then(refreshConversations)
      .catch((e: Error) => { lastSaved.current = ""; setProblem(m.saveFailed(e.message)); });
  }, [turns, busy, historyReady, conversationId, caseId, readOnly, refreshConversations]);

  // Poll uploads that are still being read, in the composer and in the conversation.
  useEffect(() => {
    const open = [...pending, ...turns.flatMap((t) => (t.role === "user" ? t.attachments : []))]
      .filter((a) => a.jobId && (a.status === "queued" || a.status === "processing"));
    if (open.length === 0) return;
    const t = setTimeout(async () => {
      const updates = new Map<string, Job>();
      await Promise.all(open.map(async (a) => {
        try { updates.set(a.jobId!, await getJob(a.jobId!)); } catch { /* try again next round */ }
      }));
      const apply = (a: Attachment): Attachment => {
        const j = a.jobId ? updates.get(a.jobId) : undefined;
        return j ? attachmentFromJob(a, j) : a;
      };
      setPending((p) => p.map(apply));
      setTurns((ts) => ts.map((t) => (t.role === "user" ? { ...t, attachments: t.attachments.map(apply) } : t)));
      if ([...updates.values()].some((j) => !["queued", "processing"].includes(j.status))) refreshDocuments();
    }, 1500);
    return () => clearTimeout(t);
  }, [pending, turns, refreshDocuments]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);

  // ---------------------------------------------------------------- derived
  // Documents used so far in this conversation, leaving out any deleted since (a reopened conversation
  // may name documents that are gone; asking about them would fail).
  const conversationDocs = useMemo(() => {
    const exists = new Set(documents.map((d) => d.id));
    const ids = new Set<string>();
    for (const t of turns) if (t.role === "user") for (const a of t.attachments)
      if (isReady(a) && a.documentId && (!documentsReady || exists.has(a.documentId))) ids.add(a.documentId);
    return ids;
  }, [turns, documents, documentsReady]);
  const filenames = useMemo(() => new Map(documents.map((d) => [d.id, d.filename])), [documents]);

  const disabledReason =
    !reachable ? m.offlineSend :
    health === null ? m.serverUnreachable :
    health.backend.status === "loading" ? m.modelStarting :
    health.status !== "ok" ? m.modelUnavailable :
    readOnly ? m.sharedReadOnly(names.get(current!.owner!) || current!.owner!) :
    closed ? m.caseIsClosed :
    currentCase && role === "reader" ? m.readerCantAsk : null;

  // ---------------------------------------------------------------- actions
  const attachFiles = async (files: File[]) => {
    for (const file of files) {
      const key = nextId();
      setPending((p) => [...p, { key, filename: file.name, status: "uploading" }]);
      try {
        const job = await uploadDocument(file, (fraction) =>
          setPending((p) => p.map((a) => (a.key === key ? { ...a, progress: fraction } : a))), caseId);
        setPending((p) => p.map((a) => (a.key === key ? attachmentFromJob({ ...a, jobId: job.id }, job) : a)));
        refreshDocuments();
      } catch (e) {
        setPending((p) => p.map((a) => (a.key === key ? { ...a, status: "failed", error: (e as Error).message } : a)));
      }
    }
  };

  const addDocument = (d: StoredDocument) => {
    if (pending.some((a) => a.documentId === d.id)) return;
    setPending((p) => [...p, { key: nextId(), filename: d.filename, status: d.status === "needs_review" ? "needs_review" : "ready",
                               documentId: d.id, reviewPages: reviewPages(d.warnings), pages: d.pages || undefined }]);
  };

  // An upload that looks like sūveryn's own output (docs/design/sidebar.md §6): the person decides.
  const useNoticedAsSource = async (key: string) => {
    const a = pending.find((x) => x.key === key);
    if (!a?.documentId) return;
    try {
      await confirmAsSource(a.documentId, caseId);
      setPending((p) => p.map((x) => (x.key === key ? { ...x, status: x.reviewPages?.length ? "needs_review" : "ready", noticed: undefined } : x)));
      refreshDocuments();
    } catch (e) { setProblem(m.useAsSourceFailed((e as Error).message)); }
  };
  const deleteNoticed = async (key: string) => {
    const a = pending.find((x) => x.key === key);
    if (!a?.documentId) return;
    try {
      await deleteDocument(a.documentId, "clean", caseId);
      setPending((p) => p.filter((x) => x.key !== key));
      refreshDocuments();
    } catch (e) { setProblem(m.deleteDocumentFailed(a.filename, (e as Error).message)); }
  };

  // ``again``: Regenerate asks the last question once more, with the documents it had.
  const send = async (text: string, again?: Attachment[]) => {
    // What is read goes with the question; a document still being read, or one that failed, stays in
    // the composer: the first counts for the next question once it is ready (§5).
    const attachments = again ?? pending.filter((a) => !staysInComposer(a));
    const user: UserTurn = { id: nextId(), role: "user", text, attachments };
    const docIds = new Set(conversationDocs);
    for (const a of attachments) if (isReady(a) && a.documentId) docIds.add(a.documentId);
    const reply: AssistantTurn = { id: nextId(), role: "assistant", text: "", citations: [], status: "streaming", grounded: docIds.size > 0 };
    const history: WireMessage[] = conversationHistory(turns);

    if (!again) setPending((p) => p.filter(staysInComposer));
    setTurns((ts) => [...ts, user, reply]);
    setBusy(true);
    setProblem(null);
    abort.current = new AbortController();
    stopped.current = false;
    const update = (patch: Partial<AssistantTurn>) =>
      setTurns((ts) => ts.map((t) => (t.id === reply.id ? ({ ...t, ...patch } as AssistantTurn) : t)));
    let streamed = "";
    let sources: Citation[] = [];
    try {
      const done = await streamChat([...history, { role: "user", content: text }], [...docIds], (delta) => {
        streamed += delta;
        update({ text: streamed });
      }, abort.current.signal, chosenModel, (step) => update({ step }), caseId, (c) => { sources = c; });
      update({ text: done.answer, citations: done.citations, calculations: done.calculations ?? [],
               unverifiedFigures: done.unverified_figures ?? [], citationIssues: done.citation_issues ?? [],
               instructionLikeSources: done.instruction_like_sources ?? [],
               status: "done", model: done.model });
    } catch (e) {
      if (stopped.current) {
        // Stopped (docs/design/sidebar.md §5): what was written stays, with the passages its markers
        // point to, marked unchecked; the server has stopped the model.
        update({ text: streamed, citations: sources, status: "stopped", step: undefined });
      } else if (streamed && (e instanceof TypeError || (e as Error).message === m.streamCutOff)) {
        // The connection dropped mid-answer (§5, artboard 09): what arrived stays, unchecked, with
        // *Regenerate*; the server is checked at once, so the bar says whether it can be reached.
        update({ text: streamed, citations: sources, status: "error", cutOff: true, error: m.answerCutOff, step: undefined });
        checkNow();
      } else {
        // Gateway contract: after an error, discard any partial answer.
        update({ text: "", status: "error", error: (e as Error).message });
        if (e instanceof TypeError) checkNow();
      }
    } finally {
      setBusy(false);
      abort.current = null;
      listModels().then(setModels).catch(() => {}); // which model is loaded may have changed
    }
  };

  // Regenerate: the last question again, with the documents it had, in place of its failed answer.
  const last = turns[turns.length - 1];
  const canRegenerate = !busy && !disabledReason && last?.role === "assistant" && last.status === "error"
    && turns[turns.length - 2]?.role === "user";
  const regenerate = () => {
    const question = turns[turns.length - 2] as UserTurn;
    setTurns((ts) => ts.slice(0, -2));
    send(question.text, question.attachments);
  };

  // The start screen: no case, nothing asked yet. First use: no conversations and no cases yet.
  const start = view === "chat" && !currentCase && turns.length === 0;
  const firstUse = start && allConversations.length === 0 && cases.length === 0;
  const firstName = (me.name || me.username).split(/\s+/)[0];
  const viewTitle = view === "conversations" ? m.conversations : view === "cases" ? m.cases : view === "documents" ? m.documents
    : view === "search" ? m.search : view === "usage" ? m.myUsage : view === "admin" ? m.administration : "";

  // The left column (docs/design/sidebar.md §2); on a narrow screen a drawer that closes once something is chosen.
  const closing = <A extends unknown[]>(f: (...a: A) => unknown) => (...a: A) => { setDrawer(false); f(...a); };
  const sidebar = (inDrawer: boolean) => (
      <Sidebar user={self} view={view} onClose={inDrawer ? () => setDrawer(false) : undefined} admin={me.admin ?? false} collapsed={inDrawer ? false : collapsed} onCollapse={setCollapsed}
               conversations={allConversations} caseConversations={conversations} documents={allDocuments} cases={cases}
               currentCase={currentCase} currentConversation={conversationId}
               casesNote={health === null || casesReady ? null : health.cases?.status === "failed" ? m.casesFailed : m.casesUnavailable}
               historyNote={health === null || historyReady ? null : health.history?.status === "failed" ? m.historyFailed : m.historyUnavailable}
               documentsNote={health === null || documentsReady ? null :
                 health.documents.status === "starting" ? m.documentsStarting :
                 health.documents.status === "unavailable" ? m.documentsUnavailable :
                 health.documents.status === "failed" ? m.documentsFailed : null}
               onNewConversation={closing((outside) => { if (outside && caseId) goTo(null); newChat(); })} onNewCase={closing(() => setNewCase(true))}
               onOpenView={closing((v: SideView) => { setOverviewFilter("all"); setView(v); })} onOpenConversation={closing(openListed)} onOpenDocument={closing(openDocument)} onOpenCase={closing(openCase)}
               onCaseAction={closing(caseAction)} tokensToday={tokensToday} activePlaybooks={activePlaybooks} onOpenUsage={closing(() => setView("usage"))}
               onOpenAdmin={closing((tab) => { setAdminTab(tab); setView("admin"); })} onOpenSettings={closing(() => setShowSettings(true))}
               onOpenAvatar={closing(() => setShowAvatar(true))} onSignOut={closing(requestSignOut)} />
  );

  // The open case's one menu: in its header, or in the top bar on a narrow screen.
  const caseMenu = currentCase && (
            <ActionMenu className="case-menu" aria-label={m.caseMenu(currentCase!.reference)} menuLabel={m.caseMenu(currentCase!.reference)}
                        placement="bottom end"
                        header={<span className="ui-menu-eyebrow">{caseTypeLabel(currentCase!.type, m)}
                          {typeof currentCase!.subject.description === "string" && ` · ${currentCase!.subject.description}`}
                          {role && ` · ${roleLabel(role, m)}`}</span>}
                        entries={[
                          { id: "members", label: m.members, icon: <Users size={16} /> },
                          ...(canShare ? [current?.shared
                            ? { id: "unshare", label: m.unshareConversation, icon: <UsersRound size={16} />, meta: m.sharedHint }
                            : { id: "share", label: m.shareConversation, icon: <Share2 size={16} /> }] : []),
                          ...(manages || administers ? [{ id: "log", label: m.accessLog, icon: <ScrollText size={16} /> }] : []),
                          ...(manages && !closed ? ["-" as const,
                            { id: "close", label: m.closeCase, icon: <Lock size={16} /> },
                            { id: "delete", label: m.deleteCase, icon: <Trash2 size={16} />, tone: "accent" as const }] : []),
                        ]}
                        onAction={(id) => {
                          if (id === "members") setShowMembers(true);
                          else if (id === "share") share(true);
                          else if (id === "unshare") share(false);
                          else if (id === "log") setShowLog(true);
                          else if (id === "close") setClosingCase(true);
                          else if (id === "delete") setDeletingCase(true);
                        }}>
              <MoreHorizontal size={16} aria-hidden />
            </ActionMenu>
  );

  // Save to case (docs/design/sidebar.md §5): a finished answer in a case, for a contributor, the case open.
  const setTurn = (id: string, patch: Partial<AssistantTurn>) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? ({ ...t, ...patch } as AssistantTurn) : t)));
  const saveControls = (t: AssistantTurn, question: string): SaveToCase | null => {
    if (!currentCase || !caseId || !contributes || closed || readOnly || t.status !== "done") return null;
    const here = savedHere.has(t.id);
    const exists = !!t.saved && (here || documents.some((d) => d.id === t.saved!.documentId));
    return {
      caseRef: currentCase.reference, saved: exists ? t.saved! : null, undoable: here && exists,
      onSave: async () => {
        try {
          const content = savedAnswer(t, question, filenames, currentCase.reference);
          const r = await saveAnswerToCase(caseId, { filename: answerFileName(question), text: searchText(content), content,
                                                    conversation_id: conversationId, message_id: t.id });
          setTurn(t.id, { saved: { documentId: r.id, filename: r.filename } });
          setSavedHere((s) => new Set(s).add(t.id));
          refreshDocuments();
        } catch (e) { setProblem(m.saveToCaseFailed((e as Error).message)); }
      },
      onOpen: () => showOverview("documents", currentCase.id),
      onUndo: async () => {
        if (!t.saved) return;
        try {
          await deleteDocument(t.saved.documentId, "clean", caseId);
          setTurn(t.id, { saved: undefined });
          setSavedHere((s) => { const n = new Set(s); n.delete(t.id); return n; });
          refreshDocuments();
        } catch (e) { setProblem(m.undoSaveFailed((e as Error).message)); }
      },
    };
  };
  // A saved answer's Word file, built again from what was saved.
  const downloadSaved = async (d: AllDocument) => {
    try {
      const { content } = await documentContent(d.id, d.case_id);
      const { saveBlob } = await import("./lib/office");
      saveBlob(d.filename, await savedWord(content, m, lang()));
    } catch (e) { setProblem(m.downloadFailedWhy((e as Error).message)); }
  };

  // Stop: the request is aborted, which closes the connection; the gateway then stops the model.
  const stop = () => {
    if (!abort.current) return;
    stopped.current = true;
    abort.current.abort();
  };
  // Esc stops an answer being written, wherever the focus is, unless a menu or dialog takes it first.
  useEffect(() => {
    if (!busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if ((e.target as Element | null)?.closest?.("[role=dialog], [role=menu], [role=listbox], [role=alertdialog]")) return;
      stop();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy]);

  // The source panel: a citation opens its source there; the same one again closes it. It closes when
  // the conversation, the place or the view changes, and with Esc when no answer is being written
  // (while one is, Esc stops it; inside the panel Esc closes the panel: Messages.tsx).
  const openSource = (turnId: string) => (s: OpenSource) =>
    setSource((cur) => (cur?.turnId === turnId && cur.n === s.n && cur.occ === s.occ ? null : { ...s, turnId }));
  useEffect(() => setSource(null), [conversationId, caseId, view]);
  useEffect(() => {
    if (!source || busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if ((e.target as Element | null)?.closest?.("[role=dialog], [role=menu], [role=listbox], [role=alertdialog]")) return;
      setSource(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [source, busy]);
  const sourceTurn = source ? turns.find((t): t is AssistantTurn => t.id === source.turnId && t.role === "assistant") : undefined;
  const sourcePanel = view === "chat" && source && sourceTurn && sourceTurn.citations[source.n - 1] && (
    <SourcePanel key={source.turnId} turn={sourceTurn} open={source} filenames={filenames} caseRef={currentCase?.reference ?? null}
                 onSource={openSource(source.turnId)} onClose={() => setSource(null)} />
  );

  const newChat = () => {
    setView("chat");
    abort.current?.abort();
    setTurns([]);
    setPending([]);
    setProblem(null);
    setConversationId(newConversationId());
    lastSaved.current = "";
    setSavedHere(new Set());
  };

  // Going to a case or the personal space without starting a chat: the lists follow `caseId`. The
  // case as the server has it now (the role may have changed since the list was read); the server
  // notes the opening in the case's access log.
  const goTo = (c: Case | null) => {
    setCurrentCase(c);
    setDocuments([]);
    setJobs([]);
    setConversations([]);
    setCaseMembers([]);
    if (c && c.my_role !== null) getCase(c.id).then((fresh) => setCurrentCase((cur) => (cur?.id === fresh.id ? fresh : cur))).catch(() => {});
    if (c && c.my_role !== null) loadMembers(c.id);
  };
  // A case's members, unless another case was opened meanwhile.
  const loadMembers = (id: string) =>
    listMembers(id).then((ms) => { if (openCaseId.current === id) setCaseMembers(ms); }).catch(() => {});
  // Opening a case or the personal space: a new chat there.
  const openCase = (c: Case | null) => {
    if ((c?.id ?? null) === caseId) { setView("chat"); return; }
    goTo(c);
    newChat();
  };
  const caseById = (id: string | null | undefined) => (id ? cases.find((c) => c.id === id) ?? null : null);
  // A conversation from a list that spans every place: go to its place first (docs/design/sidebar.md).
  const openListed = (c: ConversationSummary) => {
    const target = c.case_id ?? null;
    if (target !== caseId) goTo(caseById(target));
    setView("chat");
    openConversation(c.id);
  };
  // A document from the list of everything: go to its place, with the document ready to ask about.
  const openDocument = (d: AllDocument) => {
    const target = d.case_id ?? null;
    if (target !== caseId) { goTo(caseById(target)); newChat(); }
    setView("chat");
    if (originKind(d) === "source") addDocument(d);  // never sūveryn's own output (cases.md decision 7)
  };
  const casesWithMembers: CaseOverview[] = overviewCases
    ?? cases.map((c) => ({ ...c, members: [], last_activity_at: null, last_activity_by: "" }));
  const pin = async (c: Case, pinned: boolean) => {
    try { await pinCase(c.id, pinned); refreshCases(); } catch (e) { setProblem(m.pinFailed((e as Error).message)); }
  };
  const caseAction = (c: Case, action: CaseAction) => {
    if (action === "open") openCase(c);
    else if (action === "unpin") pin(c, false);
    else if (action === "members") { if (c.id !== caseId) goTo(c); setShowMembers(true); }
    else if (action === "log") { if (c.id !== caseId) goTo(c); setShowLog(true); }
    else if (action === "close") { if (c.id !== caseId) goTo(c); setClosingCase(true); }
  };
  const share = async (shared: boolean) => {
    try { await shareConversation(conversationId, shared); refreshConversations(); } catch (e) { setProblem(m.shareFailed((e as Error).message)); }
  };
  const removeCase = async () => {
    if (!currentCase) return;
    await deleteCase(currentCase.id);
    setDeletingCase(false);
    openCase(null);
    refreshCases();
  };
  // The case after closing, reopening or a change of its keep: shown at once, and the lists follow.
  const caseChanged = (c: Case) => {
    setCurrentCase(c);
    setCases((cs) => cs.map((x) => (x.id === c.id ? c : x)));
    refreshCases();
  };
  const shutCase = async () => {
    if (!currentCase) return;
    caseChanged(await closeCase(currentCase.id));
    setClosingCase(false);
  };

  const openConversation = async (id: string) => {
    if (id === conversationId) { setView("chat"); return; }
    try {
      const c = await getConversation(id);
      abort.current?.abort();
      const opened = fromSaved(c.turns);
      lastSaved.current = JSON.stringify(toSaved(opened));
      setConversationId(id);
      setSavedHere(new Set());
      setTurns(opened);
      setPending([]);
      setProblem(null);
    } catch (e) {
      setProblem(m.openFailed((e as Error).message));
      refreshConversations();
    }
  };

  const removeConversation = async (id: string) => {
    try {
      await deleteConversation(id);
      if (id === conversationId) newChat();
      refreshConversations();
    } catch (e) {
      setProblem(m.deleteConversationFailed((e as Error).message));
    }
  };

  // Signing out with saved conversations asks first: keep them (the default) or delete them.
  const requestSignOut = () => (historyReady && conversations.length > 0 ? setAskingSignOut(true) : signOut());
  const deleteHistoryAndSignOut = async () => {
    abort.current?.abort();
    await deleteAllConversations();
    await signOut();
  };

  // Deleting a document (suveryn-tracker#12): if saved conversations cite it, ask whether they go too.
  const [deleting, setDeleting] = useState<{ doc: StoredDocument; conversations: string[]; where: string | null } | null>(null);
  const remove = async (d: StoredDocument, where: string | null = caseId) => {
    let using: string[] = [];
    if (historyReady) {
      try { using = (await documentConversations(d.id, where)).map((c) => c.id); } catch { /* deleting still cleans them */ }
    }
    if (using.length > 0) setDeleting({ doc: d, conversations: using, where });
    else await deleteNow(d, "clean", [], where).catch((e: Error) => setProblem(m.deleteDocumentFailed(d.filename, e.message)));
  };
  // A document deleted from the list of everything (docs/design/sidebar.md): asked in its own place.
  const removeListed = (d: AllDocument) => {
    const target = d.case_id ?? null;
    if (target !== caseId) { goTo(caseById(target)); newChat(); }
    setView("chat");
    remove(d, target);
  };
  const deleteNow = async (d: StoredDocument, conversations: "clean" | "delete", using: string[], where: string | null = caseId) => {
    await deleteDocument(d.id, conversations, where);
    setPending((p) => p.filter((a) => a.documentId !== d.id));
    if (conversations === "delete" && using.includes(conversationId)) newChat();
    else if (usesDocument(turns, d.id)) setTurns((ts) => withoutDocument(ts, d.id));  // as the server cleaned it
    setDeleting(null);
    refreshDocuments();
    refreshConversations();
  };

  // ---------------------------------------------------------------- view
  return (
    <div className="app" data-sidebar={collapsed ? "collapsed" : undefined} data-panel={sourcePanel && !narrow ? true : undefined}>
{narrow
        ? <Drawer isOpen={drawer} onClose={() => setDrawer(false)} label={m.navigation}>{sidebar(true)}</Drawer>
        : sidebar(false)}
      <SettingsDialog open={showSettings} me={self} onClose={() => setShowSettings(false)}
                      onPicture={() => { setShowSettings(false); setShowAvatar(true); }} />
      <NewCaseDialog open={newCase} onCancel={() => setNewCase(false)}
                     onCreated={(c) => { setNewCase(false); setCases((cs) => [c, ...cs]); openCase(c); }} />
      <DeleteCaseDialog open={deletingCase} kase={currentCase} onDelete={removeCase} onCancel={() => setDeletingCase(false)} />
      <CloseCaseDialog open={closingCase} kase={currentCase} period={me.cases_keep} onCloseCase={shutCase} onCancel={() => setClosingCase(false)} />
      <AvatarDialog open={showAvatar} me={self} onClose={() => setShowAvatar(false)} onChanged={setAvatar} />
      {currentCase && (
        <MembersDialog open={showMembers} kase={currentCase} canManage={manages && !closed} canHandOver={manages || administers}
                       officeWide={me.office_wide ?? false} onClose={() => { setShowMembers(false); loadMembers(currentCase.id); }}
                       onChanged={(c) => { setCurrentCase(c); setCases((cs) => cs.map((x) => (x.id === c.id ? c : x))); }} />
      )}
      {currentCase && <AccessLogDialog open={showLog} kase={currentCase} onClose={() => setShowLog(false)} />}
      <DeleteDocumentDialog open={deleting !== null} filename={deleting?.doc.filename ?? ""}
                            conversations={deleting?.conversations.length ?? 0}
                            onDelete={(what) => deleteNow(deleting!.doc, what, deleting!.conversations, deleting!.where)}
                            onCancel={() => setDeleting(null)} />
      <SignOutDialog open={askingSignOut} onKeep={signOut} onDelete={deleteHistoryAndSignOut}
                     onCancel={() => setAskingSignOut(false)} />

      <main className="main" data-start={start || undefined} data-case={view === "chat" && currentCase ? true : undefined}>
        {narrow && (
          // Narrow screens (§2, artboard 15): a 56px bar with the menu button and where you are.
          <header className="top-bar">
            <IconButton label={m.openMenu} onPress={() => setDrawer(true)}><Menu size={20} aria-hidden /></IconButton>
            <span className="top-bar-where">
              {currentCase && <span className="top-bar-case">{closed ? <Lock size={12} aria-hidden /> : <Folder size={12} aria-hidden />} <b>{currentCase.reference}</b> {currentCase.name}</span>}
              <span className="top-bar-title">{view === "chat" ? (current?.title ?? (turns.length ? conversationTitle(turns) : m.newConversation)) : viewTitle}</span>
            </span>
            {view === "chat" && caseMenu}
          </header>
        )}
        {!reachable && <OfflineBar nextCheck={nextCheck} onTryNow={checkNow} />}
        {problem && <p className="banner" role="alert"><AlertCircle size={14} aria-hidden /> {problem}</p>}
        {view === "usage" && <div className="conversation"><UsageView onBack={() => setView("chat")} /></div>}
        {view === "admin" && <div className="conversation"><AdminView onBack={() => setView("chat")} initialTab={adminTab} /></div>}
        {view === "conversations" && <div className="conversation conversation-wide">
          <ConversationsOverview key={overviewFilter} initialCase={overviewFilter} conversations={allConversations} cases={casesWithMembers} me={me}
                                 onOpen={openListed} onDelete={(c) => removeConversation(c.id)} onNew={newChat} />
        </div>}
        {view === "documents" && <div className="conversation conversation-wide">
          <DocumentsOverview key={overviewFilter} initialCase={overviewFilter} onDownload={downloadSaved} me={me}
                             documents={allDocuments} jobs={jobs} jobsCase={caseId} cases={casesWithMembers} onOpen={openDocument} onDelete={removeListed}
                             onUpload={(files) => { setView("chat"); if (documentsReady) attachFiles(files); else setProblem(m.documentsCantBeAdded); }}
                             onUseAsSource={async (d) => {
                               try { await confirmAsSource(d.id, d.case_id); listAllDocuments().then(setAllDocuments).catch(() => {}); refreshDocuments(); }
                               catch (e) { setProblem(m.useAsSourceFailed((e as Error).message)); }
                             }} />
        </div>}
        {view === "cases" && <div className="conversation conversation-wide">
          <CasesOverview cases={casesWithMembers} documents={allDocuments} conversations={allConversations} officeWide={me.office_wide ?? false}
                         onOpen={openCase} onPin={pin} onNew={() => setNewCase(true)} onAction={caseAction}
                         onShowDocuments={(id) => showOverview("documents", id)} onShowConversations={(id) => showOverview("conversations", id)} />
        </div>}
        {view === "search" && <div className="conversation">
          <SearchView conversations={allConversations} documents={allDocuments} cases={cases} current={caseId}
                      onOpenConversation={openListed} onOpenDocument={openDocument} onOpenCase={openCase} onBack={() => setView("chat")} />
        </div>}
        {view === "playbook" && currentCase && (
          <div className="conversation">
            <PlaybookView kase={currentCase} canRun={contributes && !closed} documents={documents.filter((d) => originKind(d) === "source").length} onBack={() => setView("chat")} onDocumentsChanged={refreshDocuments} />
          </div>
        )}
        {view === "chat" && <>
        {currentCase && (
          // The case header (docs/design/sidebar.md §5, artboard 02): the case and its type, the
          // conversation, the members (the manager set apart), its documents and one menu for the case's actions.
          <header className="case-head">
            {closed ? <Lock size={15} aria-hidden /> : <Folder size={15} aria-hidden />}
            <span className="case-ref">{currentCase.reference}</span>
            <span className="case-name" title={currentCase.name}>{currentCase.name}</span>
            <span className="case-type">{caseTypeLabel(currentCase.type, m)}</span>
            {(current || turns.length > 0) && <>
              <span className="case-sep" aria-hidden>/</span>
              <span className="case-title">{current?.title ?? conversationTitle(turns)}</span>
            </>}
            <span className="case-space" />
            {caseMembers.length > 0 && (
              <Button variant="plain" className="case-members" onPress={() => setShowMembers(true)}
                      aria-label={m.headMembers(caseMembers.map((x) => (x.role === "manager" ? m.asManager(x.name || x.username) : x.name || x.username)).join(", "))}>
                <CaseFaces members={caseMembers} />
              </Button>
            )}
            {!administers && (
              <Button variant="plain" className="case-documents" onPress={() => showOverview("documents", currentCase.id)}
                      aria-label={m.documentsOfCase(currentCase.reference, documents.length)}>
                <FileText size={14} aria-hidden /> {m.documentCount(documents.length)}
              </Button>
            )}
            {caseMenu}
          </header>
        )}
        {currentCase && closed && (
          <CaseState kase={currentCase} canReopen={manages} canKeep={manages || administers} onChanged={caseChanged} />
        )}
        {administers ? (
          <div className="conversation">
            <div className="empty">
              <h1>{currentCase!.name}</h1>
              <p>{m.adminCaseIntro}</p>
            </div>
          </div>
        ) : <>
        <div className="conversation">
          {start ? (
            // The start screen (§2, artboards 01 and 12): a welcome over the question box; on first use the
            // two ways in.
            <div className="start" data-first={firstUse || undefined}>
              <div className="start-head"><img src={icon} width={36} height={36} alt="" /><h1>{m.welcome(firstName)}</h1></div>
              {firstUse && <>
                <p className="start-intro">{m.firstUseIntro}</p>
                <div className="start-cards">
                  <section className="start-card"><MessageSquare size={18} aria-hidden /><h2>{m.askCardTitle}</h2><p>{m.askCardText}</p></section>
                  <section className="start-card"><Folder size={18} aria-hidden /><h2>{m.caseCardTitle}</h2><p>{m.caseCardText}</p>
                    {casesReady && <Button variant="secondary" size="small" onPress={() => setNewCase(true)}><FolderPlus size={14} aria-hidden /> {m.newCase}</Button>}
                  </section>
                </div>
              </>}
            </div>
          ) : turns.length === 0 ? (
            <div className="empty">
              <h1>{currentCase ? currentCase.name : TAGLINE}</h1>
              {!closed && <p>{currentCase ? m.caseEmptyIntro : m.emptyIntro}</p>}
            </div>
          ) : (
            turns.map((t, i) => (t.role === "user" ? <UserMessage key={t.id} turn={t} /> :
              <AssistantMessage key={t.id} turn={t} filenames={filenames} caseRef={currentCase?.reference ?? null}
                                source={source?.turnId === t.id ? source : null} onSource={openSource(t.id)}
                                onRegenerate={canRegenerate && t.id === last?.id ? regenerate : null}
                                question={turns[i - 1]?.role === "user" ? turns[i - 1].text : ""}
                                save={saveControls(t, turns[i - 1]?.role === "user" ? turns[i - 1].text : "")} />))
          )}
          <div ref={endRef} />
        </div>
        <Composer attachments={pending} models={models} chosenModel={chosenModel} onChooseModel={setChosenModel} busy={busy}
                  disabledReason={disabledReason}
                  onAttach={(files) => (documentsReady ? attachFiles(files) :
                    setProblem(m.documentsCantBeAdded))}
                  onRemoveAttachment={(key) => setPending((p) => p.filter((a) => a.key !== key))}
                  onUseAsSource={useNoticedAsSource} onDeleteAttachment={deleteNoticed}
                  onSend={send} onStop={stop} caseReference={currentCase?.reference ?? null}
                  caseType={currentCase ? caseTypeLabel(currentCase.type, m) : null}
                  playbooks={administers ? [] : playbooks} onPlaybook={() => setView("playbook")}
                  compact={narrow} hint={start && firstUse ? m.personalHint : null} placeholder={start ? m.startPlaceholder : undefined}
                  workInCase={start && !firstUse && !narrow && casesReady ? { cases: cases.filter((c) => c.state === "open" && c.my_role !== null),
                                                                  onChoose: openCase, onNew: () => setNewCase(true) } : null} />
        </>}
        </>}
      </main>
      {sourcePanel && (narrow
        ? <Drawer isOpen side="right" onClose={() => setSource(null)} label={m.source(source!.n)}>{sourcePanel}</Drawer>
        : sourcePanel)}
    </div>
  );
}
