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
 * - Each question is sent with the completed earlier turns (lib/history.ts) and every document
 *   used so far in the conversation that still exists.
 * - Answers stream in as deltas; on an error event the partial text is discarded (the gateway's
 *   contract) and the turn shows an error instead.
 */
import { AlertCircle, Folder, LogIn, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDocument, documentConversations, getHealth, getJob, listDocuments, reviewPages, streamChat, uploadDocument,
  getMe, listModels, onSignedOut, signIn, signOut, type Health, type Job, type Me, type ModelInfo, type StoredDocument,
  type WireMessage, type ConversationSummary, listConversations, getConversation, saveConversation, deleteConversation,
  deleteAllConversations, getMyUsage, listCases, deleteCase, type Case,
} from "./api";
import { Lockup } from "./components/Brand";
import { caseTypeLabel, DeleteCaseDialog, NewCaseDialog } from "./components/CaseDialogs";
import { Composer } from "./components/Composer";
import { DeleteDocumentDialog } from "./components/DeleteDocumentDialog";
import { AssistantMessage, UserMessage } from "./components/Messages";
import { LanguagePicker } from "./components/LanguagePicker";
import { Sidebar } from "./components/Sidebar";
import { SignOutDialog } from "./components/SignOutDialog";
import { AdminView, UsageView } from "./components/UsageView";
import { today } from "./lib/usage";
import { conversationTitle, fromSaved, MAX_SAVED_TURNS, newConversationId, toSaved, usesDocument, withoutDocument } from "./lib/conversations";
import { conversationHistory } from "./lib/history";
import { claimRedirect, clearRedirect } from "./lib/signin";
import { locale, useT } from "./i18n";
import { Button, I18nProvider, InlineNotice, TextButton } from "./ui";
import { isPending, isReady, type AssistantTurn, type Attachment, type Turn, type UserTurn } from "./types";

const TAGLINE = "AI for work that can't leave the premises"; // English in every language, as on the website
let counter = 0;
// Unique across page loads too: turns of a reopened conversation keep the ids they were saved with.
const nextId = () => `t${Date.now().toString(36)}-${++counter}`;

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
  const [view, setView] = useState<"chat" | "usage" | "admin">("chat");
  const [tokensToday, setTokensToday] = useState<number | null>(null); // null: usage not available
  const [cases, setCases] = useState<Case[]>([]);
  const [currentCase, setCurrentCase] = useState<Case | null>(null); // null: the personal space
  const [newCase, setNewCase] = useState(false);
  const [deletingCase, setDeletingCase] = useState(false);
  const caseId = currentCase?.id ?? null;
  const lastSaved = useRef(""); // the turns as last saved (or opened), so unchanged turns aren't saved again
  const abort = useRef<AbortController | null>(null);
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

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const h = await getHealth();
      if (alive) setHealth(h);
      try { const m = await listModels(); if (alive) setModels(m); } catch { /* the health check explains why */ }
    };
    tick();
    const t = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => { if (documentsReady) refreshDocuments(); }, [documentsReady, refreshDocuments]);

  const refreshConversations = useCallback(async () => {
    try { setConversations(await listConversations(caseId)); } catch { /* the health check explains why */ }
  }, [caseId]);
  useEffect(() => { if (historyReady) refreshConversations(); }, [historyReady, refreshConversations]);

  const refreshCases = useCallback(async () => {
    try { setCases(await listCases()); } catch { /* the health check explains why */ }
  }, []);
  useEffect(() => { if (casesReady) refreshCases(); }, [casesReady, refreshCases]);

  // The sidebar's usage counter: today's own tokens, refreshed after each answer.
  useEffect(() => {
    if (busy) return;
    getMyUsage(today(new Date()).start).then((r) => setTokensToday(r.totals.total_tokens)).catch(() => setTokensToday(null));
  }, [busy]);

  // Save the conversation whenever it changed and no answer is streaming.
  useEffect(() => {
    if (!historyReady || busy || turns.length === 0) return;
    const saved = toSaved(turns);
    const body = JSON.stringify(saved);
    if (body === lastSaved.current) return;
    lastSaved.current = body;
    if (saved.length > MAX_SAVED_TURNS) { setProblem(m.saveFailed(m.conversationTooLong)); return; }  // the server refuses it
    saveConversation(conversationId, conversationTitle(turns), saved, caseId)
      .then(refreshConversations)
      .catch((e: Error) => { lastSaved.current = ""; setProblem(m.saveFailed(e.message)); });
  }, [turns, busy, historyReady, conversationId, caseId, refreshConversations]);

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
        return j ? { ...a, status: j.status, documentId: j.document_id ?? undefined, error: j.error ?? undefined,
                     reviewPages: reviewPages(j.warnings) } : a;
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
    health === null ? m.serverUnreachable :
    health.backend.status === "loading" ? m.modelStarting :
    health.status !== "ok" ? m.modelUnavailable : null;

  // ---------------------------------------------------------------- actions
  const attachFiles = async (files: File[]) => {
    for (const file of files) {
      const key = nextId();
      setPending((p) => [...p, { key, filename: file.name, status: "uploading" }]);
      try {
        const job = await uploadDocument(file, (fraction) =>
          setPending((p) => p.map((a) => (a.key === key ? { ...a, progress: fraction } : a))), caseId);
        setPending((p) => p.map((a) => (a.key === key ? { ...a, status: job.status, jobId: job.id } : a)));
        refreshDocuments();
      } catch (e) {
        setPending((p) => p.map((a) => (a.key === key ? { ...a, status: "failed", error: (e as Error).message } : a)));
      }
    }
  };

  const addDocument = (d: StoredDocument) => {
    if (pending.some((a) => a.documentId === d.id)) return;
    setPending((p) => [...p, { key: nextId(), filename: d.filename, status: d.status === "needs_review" ? "needs_review" : "ready",
                               documentId: d.id, reviewPages: reviewPages(d.warnings) }]);
  };

  const send = async (text: string) => {
    const attachments = pending.filter((a) => !isPending(a));
    const user: UserTurn = { id: nextId(), role: "user", text, attachments };
    const docIds = new Set(conversationDocs);
    for (const a of attachments) if (isReady(a) && a.documentId) docIds.add(a.documentId);
    const reply: AssistantTurn = { id: nextId(), role: "assistant", text: "", citations: [], status: "streaming", grounded: docIds.size > 0 };
    const history: WireMessage[] = conversationHistory(turns);

    setPending([]);
    setTurns((ts) => [...ts, user, reply]);
    setBusy(true);
    setProblem(null);
    abort.current = new AbortController();
    const update = (patch: Partial<AssistantTurn>) =>
      setTurns((ts) => ts.map((t) => (t.id === reply.id ? ({ ...t, ...patch } as AssistantTurn) : t)));
    let streamed = "";
    try {
      const done = await streamChat([...history, { role: "user", content: text }], [...docIds], (delta) => {
        streamed += delta;
        update({ text: streamed });
      }, abort.current.signal, chosenModel, (step) => update({ step }), caseId);
      update({ text: done.answer, citations: done.citations, calculations: done.calculations ?? [],
               unverifiedFigures: done.unverified_figures ?? [], citationIssues: done.citation_issues ?? [],
               instructionLikeSources: done.instruction_like_sources ?? [],
               status: "done", model: done.model });
    } catch (e) {
      // Gateway contract: after an error, discard any partial answer.
      update({ text: "", status: "error", error: (e as Error).message });
    } finally {
      setBusy(false);
      abort.current = null;
      listModels().then(setModels).catch(() => {}); // which model is loaded may have changed
    }
  };

  const newChat = () => {
    setView("chat");
    abort.current?.abort();
    setTurns([]);
    setPending([]);
    setProblem(null);
    setConversationId(newConversationId());
    lastSaved.current = "";
  };

  // Opening a case or the personal space: a new chat there; the sidebar's lists follow `caseId`.
  const openCase = (c: Case | null) => {
    if ((c?.id ?? null) === caseId) { setView("chat"); return; }
    setCurrentCase(c);
    setDocuments([]);
    setJobs([]);
    setConversations([]);
    newChat();
  };
  const removeCase = async () => {
    if (!currentCase) return;
    await deleteCase(currentCase.id);
    setDeletingCase(false);
    openCase(null);
    refreshCases();
  };

  const openConversation = async (id: string) => {
    if (id === conversationId) return;
    try {
      const c = await getConversation(id);
      abort.current?.abort();
      const opened = fromSaved(c.turns);
      lastSaved.current = JSON.stringify(toSaved(opened));
      setConversationId(id);
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
  const [deleting, setDeleting] = useState<{ doc: StoredDocument; conversations: string[] } | null>(null);
  const remove = async (d: StoredDocument) => {
    let using: string[] = [];
    if (historyReady) {
      try { using = (await documentConversations(d.id)).map((c) => c.id); } catch { /* deleting still cleans them */ }
    }
    if (using.length > 0) setDeleting({ doc: d, conversations: using });
    else await deleteNow(d, "clean", []).catch((e: Error) => setProblem(m.deleteDocumentFailed(d.filename, e.message)));
  };
  const deleteNow = async (d: StoredDocument, conversations: "clean" | "delete", using: string[]) => {
    await deleteDocument(d.id, conversations, caseId);
    setPending((p) => p.filter((a) => a.documentId !== d.id));
    if (conversations === "delete" && using.includes(conversationId)) newChat();
    else if (usesDocument(turns, d.id)) setTurns((ts) => withoutDocument(ts, d.id));  // as the server cleaned it
    setDeleting(null);
    refreshDocuments();
    refreshConversations();
  };

  // ---------------------------------------------------------------- view
  return (
    <div className="app">
      <Sidebar documents={documents} jobs={jobs} available={documentsReady}
               unavailableReason={health === null ? null :
                 health.documents.status === "starting" ? m.documentsStarting :
                 health.documents.status === "unavailable" ? m.documentsUnavailable :
                 health.documents.status === "failed" ? m.documentsFailed : null}
               inConversation={conversationDocs} onNewChat={newChat} onUse={addDocument} onDelete={remove}
               user={me} onSignOut={requestSignOut}
               conversations={conversations} currentConversation={conversationId}
               historyNote={health === null || historyReady ? null :
                 health.history?.status === "failed" ? m.historyFailed : m.historyUnavailable}
               onOpenConversation={(id) => { setView("chat"); openConversation(id); }} onDeleteConversation={removeConversation}
               tokensToday={tokensToday} onOpenUsage={() => setView("usage")}
               admin={me.admin ?? false} onOpenAdmin={() => setView("admin")}
               cases={cases} currentCase={currentCase} onOpenCase={openCase} onNewCase={() => setNewCase(true)}
               casesNote={health === null || casesReady ? null :
                 health.cases?.status === "failed" ? m.casesFailed : m.casesUnavailable} />
      <NewCaseDialog open={newCase} onCancel={() => setNewCase(false)}
                     onCreated={(c) => { setNewCase(false); setCases((cs) => [c, ...cs]); openCase(c); }} />
      <DeleteCaseDialog open={deletingCase} kase={currentCase} onDelete={removeCase} onCancel={() => setDeletingCase(false)} />
      <DeleteDocumentDialog open={deleting !== null} filename={deleting?.doc.filename ?? ""}
                            conversations={deleting?.conversations.length ?? 0}
                            onDelete={(what) => deleteNow(deleting!.doc, what, deleting!.conversations)}
                            onCancel={() => setDeleting(null)} />
      <SignOutDialog open={askingSignOut} onKeep={signOut} onDelete={deleteHistoryAndSignOut}
                     onCancel={() => setAskingSignOut(false)} />

      <main className="main">
        {problem && <p className="banner" role="alert"><AlertCircle size={14} aria-hidden /> {problem}</p>}
        {view === "usage" && <div className="conversation"><UsageView onBack={() => setView("chat")} /></div>}
        {view === "admin" && <div className="conversation"><AdminView onBack={() => setView("chat")} /></div>}
        {view === "chat" && <>
        {currentCase && (
          <header className="case-head">
            <Folder size={16} aria-hidden />
            <span className="case-ref">{m.caseLabel(currentCase.reference)}</span>
            <span className="case-name" title={currentCase.name}>{currentCase.name}</span>
            <span className="case-meta">{caseTypeLabel(currentCase.type, m)}
              {typeof currentCase.subject.description === "string" && ` · ${currentCase.subject.description}`}</span>
            {currentCase.my_role === "manager" && (
              <TextButton className="case-delete" onPress={() => setDeletingCase(true)}>
                <Trash2 size={14} aria-hidden /> {m.deleteCase}
              </TextButton>
            )}
          </header>
        )}
        <div className="conversation">
          {turns.length === 0 ? (
            <div className="empty">
              <h1>{currentCase ? currentCase.name : TAGLINE}</h1>
              <p>{currentCase ? m.caseEmptyIntro : m.emptyIntro}</p>
            </div>
          ) : (
            turns.map((t, i) => (t.role === "user" ? <UserMessage key={t.id} turn={t} /> :
              <AssistantMessage key={t.id} turn={t} filenames={filenames}
                                question={turns[i - 1]?.role === "user" ? turns[i - 1].text : ""} />))
          )}
          <div ref={endRef} />
        </div>
        <Composer attachments={pending} models={models} chosenModel={chosenModel} onChooseModel={setChosenModel} busy={busy}
                  disabledReason={disabledReason}
                  onAttach={(files) => (documentsReady ? attachFiles(files) :
                    setProblem(m.documentsCantBeAdded))}
                  onRemoveAttachment={(key) => setPending((p) => p.filter((a) => a.key !== key))}
                  onSend={send} />
        </>}
      </main>
    </div>
  );
}
