/**
 * A playbook is a conversation (Filip, 30 October 2026; docs/design/playbooks.md, "The chat UI"; boards
 * 52 to 54). Starting one from the composer's *Playbook* menu makes a new conversation in the case,
 * titled with the playbook; it is listed with the case's other conversations and opens here. The
 * playbook speaks as sūveryn (the mark with the route badge, the playbook's title as speaker), people
 * answer in the composer in their own words, the documents come in through the paperclip, and the facts
 * sit in a panel beside the conversation, where they are checked, changed and confirmed.
 *
 * The run's turns are rows the server writes (``turns``); the playbook's own lines carry a ``meta.kind``
 * the thread words in the interface language (``ask``, ``checkpoint``, ``changed``, ``unplaced``, and the
 * events ``paused``, ``resumed``, ``stopped``, ``cancelled``, ``confirmed``), the pack's questions are
 * shown as written. Pause, cancel and stop are on the run's chip in the composer, shown only to those the
 * gateway would allow (it decides; the chip hides what would fail).
 */
import {
  ArrowLeft, ArrowUp, Check, ChevronDown, CircleAlert, CircleX, Download, FileText, Paperclip, Pause, Play, Route, Square, TriangleAlert, X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  confirmRun, getJob, getRun, isArchiveUpload, runAction, sayInRun, uploadDocument,
  type Case, type Citation, type Job, type PlaybookInfo, type Run, type RunFact, type RunStatus, type RunSummary, type RunTurn,
} from "../api";
import { useWatermark } from "../lib/watermark";
import { locale, useT } from "../i18n";
import type { PlaybookWords } from "../lib/playbooks";
import { ACCEPTED_FILES } from "../lib/formats";
import { exportRef } from "../lib/marks";
import { ActionMenu, Button, Dialog, IconBadge, IconButton, InlineNotice, TextArea, TextButton, useFilePicker, type MenuEntry } from "../ui";
import { AssistantMark } from "./Brand";
import { SourceCard } from "./Messages";

const POLL_MS = 1500;
const LIVE: RunStatus[] = ["reading", "waiting", "paused"];
type Words = ReturnType<typeof useT>;

// ------------------------------------------------------------------ words shared with the case lists

export function statusLabel(status: RunStatus, m: Words): string {
  return { reading: m.runReading, waiting: m.runWaiting, paused: m.runPaused, done: m.runDone, stopped: m.runStopped,
           cancelled: m.runCancelled, failed: m.runFailed }[status] ?? status;
}

/** The step's kind, from the playbook's routine (the server also sends it as ``step_kind``). */
export function stepKind(run: Pick<RunSummary, "step" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined): string | null {
  return run.step_kind ?? playbook?.steps?.find((s) => s.id === run.step)?.kind ?? null;
}

/** The step's name, for the chip on a case: the kind in words, since the playbook names its steps for the machine. */
export function stepLabel(run: Pick<RunSummary, "step" | "status" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words): string {
  const kind = stepKind(run, playbook);
  if (run.status === "reading" || kind === "read") return m.stepReading;
  const names: Record<string, string> = { request: m.stepRequest, ask: m.stepAsk, checkpoint: m.stepCheckpoint, produce: m.stepProduce };
  return names[kind ?? ""] ?? "";
}

/** One line for the chip on a case in the case lists: the playbook's title and what the run waits for. */
export function runChipText(run: RunSummary, playbook: Pick<PlaybookInfo, "steps" | "name" | "text"> | null | undefined, title: string, m: Words, lang?: string): string {
  const name = (lang && run.title?.[lang]) || run.title?.en || title;
  const what = run.status === "paused" ? m.runPaused : stepLabel(run, playbook, m);
  return what ? `${name} · ${what}` : name;
}

function errorLabel(error: string | null, m: Words): string {
  const known: Record<string, string> = {
    unreadable_answer: m.runErrorUnreadable, model_unavailable: m.runErrorModel, documents_unavailable: m.runErrorDocuments,
    interrupted: m.runErrorInterrupted, busy: m.runErrorBusy, document_missing: m.runErrorDocuments, server_error: m.runErrorServer,
  };
  return known[error ?? ""] ?? m.runErrorServer;
}

const time = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" }) : "";
const dayAndTime = (iso: string) => {
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? time(iso) : `${d.toLocaleDateString(locale(), { day: "numeric", month: "short" })} ${time(iso)}`;
};

/** How many facts have a value, of how many. */
export const factCounts = (run: Pick<Run, "facts">) => [run.facts.filter((f) => (f.confirmed ?? f.value)).length, run.facts.length] as const;

// ------------------------------------------------------------------ the run, kept fresh

/** The open run, polled while it is live so a colleague's answer or the model's reading shows up. */
export function useRun(caseId: string | null, runId: string | null) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRun(null);
    setError(null);
    if (!caseId || !runId) return;
    getRun(caseId, runId).then(setRun).catch((e: Error) => setError(e.message));
  }, [caseId, runId]);
  useEffect(() => {
    if (!caseId || !run || run.id !== runId || !LIVE.includes(run.status)) return;
    const t = window.setTimeout(() => {
      getRun(caseId, run.id).then(setRun).catch((e: Error) => setError(e.message));
    }, run.status === "reading" ? POLL_MS : POLL_MS * 4);
    return () => window.clearTimeout(t);
  }, [caseId, runId, run]);
  return { run: run && run.id === runId ? run : null, setRun, error };
}

// ------------------------------------------------------------------ the conversation

export function RunThread({ run, kase, playbook, words, me, canAnswer, nameOf, factsOpen, onChanged, onOpenFacts, onRestart, onDocumentsChanged }: {
  run: Run; kase: Case; playbook: PlaybookInfo | null; words: PlaybookWords; me?: string;
  /** A contributor of an open case: answers, confirms, pauses (the gateway decides; this only hides). */
  canAnswer: boolean;
  /** A username as the case knows the person (the run records usernames). */
  nameOf: (username: string) => string;
  factsOpen: boolean;
  onChanged: (run: Run) => void;
  onOpenFacts: () => void;
  /** Start the playbook again (a new conversation): after an error. */
  onRestart?: () => void;
  onDocumentsChanged: () => void;
}) {
  const m = useT();
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [run.turns.length, run.status]);
  const title = words.title || playbook?.name || "";
  const [found, total] = factCounts(run);
  const speaker = (i: number) => {
    const before = run.turns[i - 1];
    return !before || before.role !== "playbook" || isEvent(before);
  };
  return (
    <>
      <div className="conversation run-thread" aria-live="polite">
        <p className="run-line">{m.runStartLine(nameOf(run.started_by), title, run.playbook_version, dayAndTime(run.started_at))}</p>
        {playbook && !playbook.covered && <InlineNotice icon={<TriangleAlert size={14} />}>{m.playbookNotCovered}</InlineNotice>}
        {run.out_of_date && <InlineNotice icon={<TriangleAlert size={14} />}>{m.runOutOfDateHint}</InlineNotice>}
        {run.instruction_like_sources.length > 0 && <InlineNotice icon={<TriangleAlert size={14} />}>{m.runSuspiciousSources}</InlineNotice>}
        {run.turns.map((t, i) => (isEvent(t)
          ? <EventLine key={t.seq} turn={t} nameOf={nameOf} />
          : t.role === "user"
            ? <PersonTurn key={t.seq} turn={t} nameOf={nameOf} />
            : <PlaybookTurn key={t.seq} turn={t} title={title} showSpeaker={speaker(i)} words={words}
                            chip={t.meta.kind === "checkpoint" && run.facts.length > 0
                              ? { label: m.factsChip(words.facts_title || m.factsPanel, found, total), open: factsOpen, onPress: onOpenFacts } : null}
                            quickReply={t.meta.kind === "ask" && canAnswer && run.status === "waiting" && i === run.turns.length - 1
                              ? () => sayInRun(kase.id, run.id, { text: m.answerPlaceholder, unknown: true }).then(onChanged) : null} />))}
        {run.status === "reading" && (
          <div className="turn-assistant">
            <Speaking />
            <p className="waiting" role="status"><span className="waiting-dots" aria-hidden><i /><i /><i /></span>
              <span>{m.runReadingTurn(run.documents.length || 1)}</span></p>
          </div>
        )}
        {run.status === "failed" && (
          <div className="turn-assistant">
            <Speaking />
            <p className="answer-failed"><CircleX size={14} aria-hidden /><span>{errorLabel(run.error, m)}</span>
              {onRestart && canAnswer && <TextButton link onPress={onRestart}>{m.retryRun}</TextButton>}</p>
          </div>
        )}
        {run.status === "done" && <SummaryTurn run={run} kase={kase} words={words} nameOf={nameOf} title={title} />}
        <div ref={end} />
      </div>
      <RunComposer run={run} kase={kase} playbook={playbook} title={title} me={me} canAnswer={canAnswer}
                   onChanged={onChanged} onDocumentsChanged={onDocumentsChanged} />
    </>
  );
}

const EVENTS = new Set(["paused", "resumed", "stopped", "cancelled", "confirmed"]);
const isEvent = (t: RunTurn) => t.role === "playbook" && typeof t.meta.kind === "string" && EVENTS.has(t.meta.kind);

/** The brand mark with the route badge: a playbook speaking (badge-icon, system). */
function Speaking() {
  return <IconBadge badge={<Route />} host="icon" tone="system"><AssistantMark /></IconBadge>;
}

function PlaybookTurn({ turn, title, showSpeaker, words, chip, quickReply }: {
  turn: RunTurn; title: string; showSpeaker: boolean; words: PlaybookWords;
  chip: { label: string; open: boolean; onPress: () => void } | null;
  quickReply: (() => Promise<void>) | null;
}) {
  const m = useT();
  const [sending, setSending] = useState(false);
  const meta = turn.meta as { kind?: string; facts?: string[]; found?: number; total?: number; issues?: number; fact?: string; value?: string };
  const label = (id: string) => words.labels[id] ?? id;
  const text = meta.kind === "ask" ? m.runAskTurn(meta.found ?? 0, meta.total ?? 0, (meta.facts ?? []).map(label).join(", "))
    : meta.kind === "checkpoint" ? m.runCheckpointTurn(meta.found ?? 0, meta.total ?? 0) + (meta.issues ? ` ${m.runCheckpointIssues(meta.issues)}` : "")
    : meta.kind === "changed" ? m.runChanged(label(meta.fact ?? ""), meta.value ?? "")
    : meta.kind === "unplaced" ? (meta.facts ? m.runUnplacedAsk : m.runUnplacedChange)
    : turn.text;
  return (
    <div className="turn-assistant run-turn">
      <Speaking />
      <div className="answer">
        {showSpeaker && <p className="run-speaker">{title}</p>}
        <p>{text}</p>
        {chip && (
          <Button variant="plain" className="chip-facts" onPress={chip.onPress} aria-expanded={chip.open}>
            <FileText size={13} aria-hidden /> {chip.label}
          </Button>
        )}
        {quickReply && (
          <div className="run-quick">
            <Button variant="secondary" size="small" isDisabled={sending}
                    onPress={() => { setSending(true); quickReply().finally(() => setSending(false)); }}>{m.answerPlaceholder}</Button>
          </div>
        )}
      </div>
    </div>
  );
}

function PersonTurn({ turn, nameOf }: { turn: RunTurn; nameOf: (u: string) => string }) {
  const attachments = (turn.meta.attachments as { documentId: string; filename: string }[] | undefined) ?? [];
  return (
    <div className="turn-user">
      {attachments.length > 0 && (
        <div className="attachments">
          {attachments.map((a) => <span key={a.documentId} className="chip-attachment"><FileText size={13} aria-hidden /> {a.filename}</span>)}
        </div>
      )}
      {turn.text && <div className="bubble">{turn.text}</div>}
      <span className="caption">{nameOf(turn.by)} · {dayAndTime(turn.at)}</span>
    </div>
  );
}

/** Paused, resumed, stopped, cancelled, confirmed: a centred line with its icon; "Confirmed" in teal (a system status). */
function EventLine({ turn, nameOf }: { turn: RunTurn; nameOf: (u: string) => string }) {
  const m = useT();
  const who = nameOf(turn.by), at = dayAndTime(turn.at);
  const kind = turn.meta.kind as string;
  const [icon, text] = kind === "confirmed" ? [<Check size={13} key="i" />, m.runConfirmedLine(who, at)]
    : kind === "paused" ? [<Pause size={13} key="i" />, m.runPausedLine(who, at)]
    : kind === "resumed" ? [<Play size={13} key="i" />, m.runResumedLine(who, at)]
    : kind === "stopped" ? [<Square size={13} key="i" />, m.runStoppedLine(who, at)]
    : [<CircleX size={13} key="i" />, m.runCancelledLine(who, at, String(turn.meta.reason ?? ""))];
  return <p className="run-line" data-kind={kind}><span aria-hidden>{icon}</span> {text}</p>;
}

/** Done: the summary as a document card (Gemaakt) with its Word download. */
function SummaryTurn({ run, kase, words, nameOf, title }: { run: Run; kase: Case; words: PlaybookWords; nameOf: (u: string) => string; title: string }) {
  const m = useT();
  const mark = useWatermark();
  const word = async () => {
    const { intakeToWord, saveBlob } = await import("../lib/office");
    const blob = await intakeToWord({
      title: `${title} ${kase.reference}`, caseName: kase.name, version: m.playbookVersion(run.playbook_version),
      confirmedOn: m.confirmedBy(run.confirmed_by ? nameOf(run.confirmed_by) : "", new Date(run.confirmed_at ?? run.started_at).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" })),
      facts: run.facts.map((f) => ({ label: words.labels[f.id] ?? f.id, value: f.confirmed ?? f.value,
                                    sources: f.citations.map((c) => `${c.filename}${c.page ? ` p. ${c.page}` : ""}`) })),
      sourcesHeading: m.sourcesHeading, emptyValue: m.factNotFound, disclaimer: m.wordDisclaimer,
      // sūveryn's mark (lib/marks.ts): uploaded again, this file asks before it becomes a source
      mark: m.exportMark("playbook", kase.reference, new Date().toLocaleDateString(locale()), exportRef("P", run.id))
        + (mark() ? ` · ${m.strictlyConfidential}` : ""),
      watermark: mark(),  // a strictly confidential case (§11)
    });
    saveBlob(`${title} ${kase.reference}.docx`.replace(/[/\\]/g, "-"), blob);
  };
  return (
    <div className="turn-assistant run-turn">
      <Speaking />
      <div className="answer">
        <div className="run-summary-card">
          <FileText size={16} aria-hidden />
          <span className="run-summary-name"><b>{m.runSummaryCard}</b> {title} {kase.reference}</span>
          {run.result_document_id && <span className="caption">{m.summaryInCase}</span>}
        </div>
        <div className="answer-actions">
          <Button variant="plain" className="copy-button" onPress={word}><Download size={14} aria-hidden /> {m.downloadWord}</Button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the composer, with the run's chip

function RunComposer({ run, kase, playbook, title, me, canAnswer, onChanged, onDocumentsChanged }: {
  run: Run; kase: Case; playbook: PlaybookInfo | null; title: string; me?: string; canAnswer: boolean;
  onChanged: (run: Run) => void; onDocumentsChanged: () => void;
}) {
  const m = useT();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const kind = stepKind(run, playbook);
  const live = LIVE.includes(run.status);
  const mayEnd = live && (run.starter === me || kase.manager === me);
  const waiting = run.status === "waiting";

  const act = async (action: "pause" | "resume" | "stop" | "cancel") => {
    setBusy(true);
    setError(null);
    try { onChanged(await runAction(kase.id, run.id, action, action === "cancel" ? reason : "")); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); setCancelling(false); setReason(""); }
  };
  const say = async (said: { text?: string; documents?: string[] }) => {
    setBusy(true);
    setError(null);
    try { onChanged(await sayInRun(kase.id, run.id, said)); setText(""); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  // The documents go into the case first, are read there, then come with the person's turn.
  const upload = async (files: File[]) => {
    setError(null);
    setUploading(files.map((f) => f.name));
    const ids: string[] = [];
    try {
      const jobs: Job[] = [];
      for (const f of files) {
        const r = await uploadDocument(f, undefined, kase.id);
        jobs.push(...(isArchiveUpload(r) ? r.jobs : [r]));
      }
      for (let job of jobs) {
        while (job.status === "queued" || job.status === "processing") {
          await new Promise((ok) => window.setTimeout(ok, 1000));
          job = await getJob(job.id);
        }
        if (job.document_id && (job.status === "ready" || job.status === "needs_review")) ids.push(job.document_id);
      }
    } catch (e) { setError((e as Error).message); }
    setUploading([]);
    onDocumentsChanged();
    if (ids.length) await say({ text: text.trim(), documents: ids });
  };
  const picker = useFilePicker(ACCEPTED_FILES, true, (files) => void upload(files));
  const send = () => { if (text.trim() && !busy) void say({ text: text.trim() }); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
  };

  const menu: MenuEntry[] = run.status === "paused"
    ? [{ id: "resume", label: m.resumeRun, icon: <Play size={16} /> }]
    : [{ id: "pause", label: m.pauseRun, icon: <Pause size={16} />, description: m.pauseRunHint, isDisabled: !waiting },
       ...(mayEnd ? [{ id: "cancel", label: m.cancelRunMenu, icon: <CircleX size={16} />, description: m.cancelRunMenuHint },
                     { id: "stop", label: m.stopRun, icon: <Square size={16} />, description: m.stopRunMenuHint }] as MenuEntry[] : [])];
  const chip = live && (
    canAnswer ? (
      <ActionMenu className="chip-run" data-status={run.status} aria-label={run.status === "paused" ? m.runChipPaused(title, run.playbook_version) : m.runChipRunning(title, run.playbook_version)}
                  menuLabel={m.runMenu} placement="top start" entries={menu} isDisabled={busy}
                  onAction={(id) => { if (id === "cancel") setCancelling(true); else void act(id as "pause" | "resume" | "stop"); }}>
        {run.status === "paused" ? <Pause size={13} aria-hidden /> : <Route size={13} aria-hidden />}
        {run.status === "paused" ? m.runChipPaused(title, run.playbook_version) : m.runChipRunning(title, run.playbook_version)}
        <ChevronDown size={13} aria-hidden />
      </ActionMenu>
    ) : (
      <span className="chip-run" data-status={run.status}>
        {run.status === "paused" ? <Pause size={13} aria-hidden /> : <Route size={13} aria-hidden />}
        {run.status === "paused" ? m.runChipPaused(title, run.playbook_version) : m.runChipRunning(title, run.playbook_version)}
      </span>
    )
  );
  const line = !live ? null
    : run.status === "paused" ? m.runPausedLine2(title)
    : run.status === "reading" ? m.runReadingLine(title)
    : kind === "checkpoint" ? m.runWaitsOnYou(title, m.runWaitsCheck)
    : kind === "request" ? m.runWaitsOnYou(title, m.runWaitsDocuments)
    : kind === "ask" ? m.runWaitsOnYou(title, m.runWaitsAnswers) : null;

  if (!canAnswer) {
    return (
      <div className="composer-wrap">
        {chip && <div className="run-chips">{chip}</div>}
        <p className="composer-hint caption" role="status">{live ? m.runReadOnly : null}</p>
      </div>
    );
  }
  if (!live) return null;
  return (
    <div className="composer-wrap">
      {uploading.length > 0 && (
        <ul className="attachment-cards">{uploading.map((n) => <li key={n} className="chip-attachment"><Paperclip size={13} aria-hidden /> {m.uploadingFile(n)}</li>)}</ul>
      )}
      <div className="composer">
        <TextArea label={title} hideLabel value={text} onChange={setText} onKeyDown={onKey} isReadOnly={!waiting}
                  placeholder={waiting ? m.runAnswerPlaceholder : ""} className="composer-field" />
        <div className="composer-tools">
          {picker.input}
          <IconButton size="small" label={m.addDocuments} onPress={() => picker.open()} isDisabled={!waiting || busy || uploading.length > 0}>
            <Paperclip size={16} aria-hidden />
          </IconButton>
          {chip}
          <span className="composer-space" />
          <Button variant="plain" className="send-button" onPress={send} isDisabled={!waiting || busy || !text.trim()} aria-label={m.send}>
            <ArrowUp size={16} strokeWidth={2.2} aria-hidden />
          </Button>
        </div>
      </div>
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      <p className="composer-hint caption" role="status">{line}</p>
      <Dialog isOpen={cancelling} onClose={() => setCancelling(false)} title={m.cancelRun} busy={busy}
              actions={<>
                <Button variant="secondary" onPress={() => setCancelling(false)}>{m.keepRunning}</Button>
                <Button variant="primary" onPress={() => void act("cancel")} isDisabled={busy}>{m.cancelRunConfirm}</Button>
              </>}>
        <p>{m.cancelRunExplain}</p>
        <TextArea label={m.cancelReason} value={reason} onChange={setReason} rows={2} className="ui-field playbook-reason" />
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ the facts panel

export function FactsPanel({ run, kase, words, canConfirm, nameOf, onChanged, onClose }: {
  run: Run; kase: Case; words: PlaybookWords; canConfirm: boolean; nameOf: (u: string) => string;
  onChanged: (run: Run) => void; onClose: () => void;
}) {
  const m = useT();
  const [values, setValues] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [passage, setPassage] = useState<RunFact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLElement>(null);
  const [found, total] = factCounts({ facts: run.facts.map((f) => ({ ...f, value: values[f.id] ?? f.value })) });
  const atCheckpoint = run.status === "waiting" && run.facts.length > 0 && run.confirmed_at === null && canConfirm && run.step !== null
    && run.turns.some((t) => t.meta.kind === "checkpoint" && t.step_id === run.step);
  // a value changed by someone else (or in words) since: the panel follows, unless this person is changing it
  const value = (f: RunFact) => values[f.id] ?? f.confirmed ?? f.value;
  useEffect(() => { panel.current?.focus(); }, []);
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Escape" || editing) return;
    if ((e.target as Element | null)?.closest?.("[role=dialog], [role=menu]")) return;
    e.stopPropagation();
    if (passage) setPassage(null); else onClose();
  };
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await confirmRun(kase.id, run.id, run.facts.map((f) => ({ id: f.id, confirmed: value(f) }))));
      setValues({});
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const close = useCallback(onClose, [onClose]);
  const title = words.facts_title || m.factsPanel;
  return (
    <aside className="source-panel facts-panel" ref={panel} tabIndex={-1} aria-label={title} onKeyDown={onKeyDown}>
      <header className="source-panel-head">
        {passage ? (
          <TextButton onPress={() => setPassage(null)}><ArrowLeft size={14} aria-hidden /> {m.backToFacts}</TextButton>
        ) : (
          <span className="source-panel-title">
            <span className="source-panel-file">{title}</span>
            <span className="source-panel-count">{m.factsCount(found, total)}</span>
          </span>
        )}
        <span className="composer-space" />
        <IconButton label={m.close} onPress={close}><X size={16} aria-hidden /></IconButton>
      </header>
      <div className="source-panel-body">
        {passage ? <Passage fact={passage} /> : (
          <ol className="facts">
            {run.facts.map((f) => (
              <FactRow key={f.id} fact={f} label={words.labels[f.id] ?? f.id} value={value(f)} nameOf={nameOf}
                       editable={atCheckpoint} editing={editing === f.id}
                       onEdit={() => setEditing(f.id)} onDone={(v) => { if (v !== null) setValues((vs) => ({ ...vs, [f.id]: v })); setEditing(null); }}
                       onPassage={() => setPassage(f)} confirmed={run.confirmed_at !== null && f.confirmed !== null} />
            ))}
          </ol>
        )}
      </div>
      {atCheckpoint && !passage && (
        <footer className="facts-foot">
          {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
          <Button variant="primary" onPress={() => void confirm()} isDisabled={busy}>{busy ? m.saving : m.confirmAll}</Button>
          <p className="caption">{m.clickToChange}</p>
        </footer>
      )}
    </aside>
  );
}

function FactRow({ fact, label, value, nameOf, editable, editing, onEdit, onDone, onPassage, confirmed }: {
  fact: RunFact; label: string; value: string; nameOf: (u: string) => string; editable: boolean; editing: boolean;
  onEdit: () => void; onDone: (value: string | null) => void; onPassage: () => void; confirmed: boolean;
}) {
  const m = useT();
  const [draft, setDraft] = useState(value);
  useEffect(() => { if (editing) setDraft(value); }, [editing, value]);
  const first = fact.citations[0];
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onDone(draft.trim()); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onDone(null); }
  };
  const shown = value
    ? <span className="fact-value">{value}</span>
    : <em className="fact-value fact-unknown">{m.answerPlaceholder}</em>;
  return (
    <li className="fact" data-confirmed={confirmed || undefined}>
      <span className="fact-label">{label}</span>
      <div className="fact-row">
        {editing ? (
          <TextArea label={m.changeValue(label, value)} hideLabel value={draft} onChange={setDraft} onKeyDown={onKey} rows={1}
                    className="playbook-fact-field" />
        ) : editable ? (
          <Button variant="plain" className="fact-edit" onPress={onEdit} aria-label={m.changeValue(label, value || m.answerPlaceholder)}>{shown}</Button>
        ) : shown}
        {confirmed && <Check size={14} className="fact-check" aria-label={m.factConfirmed} />}
        {first && (
          <Button variant="plain" className="cite-marker fact-source" onPress={onPassage}
                  aria-label={m.sourceLabel(first.n, first.filename, first.page)}>{first.n}</Button>
        )}
      </div>
      {fact.issues.length > 0 && <span className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {m.factCheckThis}</span>}
      {fact.source === "person" && fact.by && !fact.was && <span className="fact-note">{m.factFromPersonIn(nameOf(fact.by))}</span>}
      {fact.source === "person" && fact.was && <span className="fact-note">{m.factChangedIn(fact.was)}</span>}
    </li>
  );
}

function Passage({ fact }: { fact: RunFact }) {
  const first = fact.citations[0];
  const citation: Citation = { text: first.text, source: { document_id: first.document_id, page: first.page, location: first.location } };
  return <SourceCard n={first.n} citation={citation} filename={first.filename} claims={[fact.value]} />;
}
