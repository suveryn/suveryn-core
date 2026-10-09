import { AlertCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDocument, getHealth, getJob, listDocuments, streamChat, uploadDocument,
  type Health, type Job, type StoredDocument, type WireMessage,
} from "./api";
import { Composer } from "./components/Composer";
import { AssistantMessage, UserMessage } from "./components/Messages";
import { Sidebar } from "./components/Sidebar";
import { stripMarkers } from "./lib/answer";
import { isPending, isReady, type AssistantTurn, type Attachment, type Turn, type UserTurn } from "./types";

const TAGLINE = "AI for work that can't leave the premises";
let counter = 0;
const nextId = () => `t${++counter}`;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState<Attachment[]>([]); // attachments for the next message
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const documentsReady = health?.documents.status === "ready";

  // ---------------------------------------------------------------- server state
  const refreshDocuments = useCallback(async () => {
    try {
      const r = await listDocuments();
      setDocuments(r.documents);
      setJobs(r.jobs);
    } catch { /* document handling unavailable; the health check explains why */ }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { const h = await getHealth(); if (alive) setHealth(h); };
    tick();
    const t = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => { if (documentsReady) refreshDocuments(); }, [documentsReady, refreshDocuments]);

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
        return j ? { ...a, status: j.status, documentId: j.document_id ?? undefined, error: j.error ?? undefined } : a;
      };
      setPending((p) => p.map(apply));
      setTurns((ts) => ts.map((t) => (t.role === "user" ? { ...t, attachments: t.attachments.map(apply) } : t)));
      if ([...updates.values()].some((j) => !["queued", "processing"].includes(j.status))) refreshDocuments();
    }, 1500);
    return () => clearTimeout(t);
  }, [pending, turns, refreshDocuments]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);

  // ---------------------------------------------------------------- derived
  const conversationDocs = useMemo(() => {
    const ids = new Set<string>();
    for (const t of turns) if (t.role === "user") for (const a of t.attachments) if (isReady(a) && a.documentId) ids.add(a.documentId);
    return ids;
  }, [turns]);
  const filenames = useMemo(() => new Map(documents.map((d) => [d.id, d.filename])), [documents]);

  const disabledReason =
    health === null ? "Can't reach the Sūveryn server." :
    health.backend.status === "loading" ? "The model is starting. This takes up to a minute." :
    health.status !== "ok" ? "The model isn't available right now." : null;

  // ---------------------------------------------------------------- actions
  const attachFiles = async (files: File[]) => {
    for (const file of files) {
      const key = nextId();
      setPending((p) => [...p, { key, filename: file.name, status: "uploading" }]);
      try {
        const job = await uploadDocument(file);
        setPending((p) => p.map((a) => (a.key === key ? { ...a, status: job.status, jobId: job.id } : a)));
        refreshDocuments();
      } catch (e) {
        setPending((p) => p.map((a) => (a.key === key ? { ...a, status: "failed", error: (e as Error).message } : a)));
      }
    }
  };

  const addDocument = (d: StoredDocument) => {
    if (pending.some((a) => a.documentId === d.id)) return;
    setPending((p) => [...p, { key: nextId(), filename: d.filename, status: d.status === "needs_review" ? "needs_review" : "ready", documentId: d.id }]);
  };

  const send = async (text: string) => {
    const attachments = pending.filter((a) => !isPending(a));
    const user: UserTurn = { id: nextId(), role: "user", text, attachments };
    const docIds = new Set(conversationDocs);
    for (const a of attachments) if (isReady(a) && a.documentId) docIds.add(a.documentId);
    const reply: AssistantTurn = { id: nextId(), role: "assistant", text: "", citations: [], status: "streaming", grounded: docIds.size > 0 };
    const history: WireMessage[] = turns
      .filter((t) => t.role === "user" || t.status === "done")
      .map((t) => ({ role: t.role, content: t.role === "assistant" ? stripMarkers(t.text) : t.text }));

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
      }, abort.current.signal);
      update({ text: done.answer, citations: done.citations, status: "done", model: done.model });
    } catch (e) {
      // Gateway contract: after an error, discard any partial answer.
      update({ text: "", status: "error", error: (e as Error).message });
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  const newChat = () => {
    abort.current?.abort();
    setTurns([]);
    setPending([]);
    setProblem(null);
  };

  const remove = async (d: StoredDocument) => {
    try {
      await deleteDocument(d.id);
      setPending((p) => p.filter((a) => a.documentId !== d.id));
      refreshDocuments();
    } catch (e) {
      setProblem(`Couldn't delete ${d.filename}: ${(e as Error).message}`);
    }
  };

  // ---------------------------------------------------------------- view
  return (
    <div className="app">
      <Sidebar documents={documents} jobs={jobs} available={documentsReady}
               unavailableReason={health === null ? null :
                 health.documents.status === "starting" ? "Document handling is starting…" :
                 health.documents.status === "unavailable" ? "Document handling isn't available on this server." :
                 health.documents.status === "failed" ? "Document handling failed to start." : null}
               inConversation={conversationDocs} onNewChat={newChat} onUse={addDocument} onDelete={remove} />

      <main className="main">
        {problem && <p className="banner" role="alert"><AlertCircle size={14} aria-hidden /> {problem}</p>}
        <div className="conversation">
          {turns.length === 0 ? (
            <div className="empty">
              <h1>{TAGLINE}</h1>
              <p>Attach a deed or another PDF and ask about it. Answers cite the page they come from, so you can check every figure.</p>
            </div>
          ) : (
            turns.map((t) => (t.role === "user" ? <UserMessage key={t.id} turn={t} /> :
              <AssistantMessage key={t.id} turn={t} filenames={filenames} />))
          )}
          <div ref={endRef} />
        </div>
        <Composer attachments={pending} model={health?.backend.model ?? null} busy={busy}
                  disabledReason={disabledReason}
                  onAttach={(files) => (documentsReady ? attachFiles(files) :
                    setProblem("Documents can't be added right now: document handling isn't available on this server."))}
                  onRemoveAttachment={(key) => setPending((p) => p.filter((a) => a.key !== key))}
                  onSend={send} />
      </main>
    </div>
  );
}
