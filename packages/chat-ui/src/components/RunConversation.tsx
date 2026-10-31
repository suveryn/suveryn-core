/**
 * A playbook is a conversation (Filip, 30 October 2026; docs/design/playbooks.md, "The chat UI"; boards
 * 52 to 54). Starting one from the composer's *Playbook* menu makes a new conversation in the case,
 * titled with the playbook; it is listed with the case's other conversations and opens here. The
 * playbook speaks as sūveryn (the mark with the route badge, the playbook's title as speaker), people
 * answer in the composer in their own words, and the documents come in through the paperclip. At review the
 * work comes to the playbook's message (handover of 31 October 2026): one card per fact that needs the
 * person (*Check*, *Missing*), changed in place, and *Confirm the facts*; every fact is in a reference list
 * in the panel beside the conversation, nothing edited there. Sources look the same as under an answer.
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
import { useId } from "react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  confirmRun, getJob, getRun, isArchiveUpload, runAction, sayInRun, setRunFact, uploadDocument,
  type Case, type Citation, type Job, type PlaybookInfo, type Run, type RunFact, type RunStatus, type RunSummary, type RunTurn,
} from "../api";
import { useWatermark } from "../lib/watermark";
import { locale, useT } from "../i18n";
import type { PlaybookWords } from "../lib/playbooks";
import { ACCEPTED_FILES } from "../lib/formats";
import { exportRef } from "../lib/marks";
import {
  ActionMenu, Button, Card, Dialog, IconBadge, IconButton, InlineNotice, SourceRef, TextArea, TextButton, useFilePicker, type MenuEntry,
} from "../ui";
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

/** The facts a review card is for (handover of 31 October 2026): *Check*, a value the check couldn't find
 *  literally in its passage and nobody has checked since; *Missing*, a fact without a value. */
export function reviewGroups(run: Pick<Run, "facts">): { check: RunFact[]; missing: RunFact[] } {
  return { check: run.facts.filter((f) => f.value && f.issues.length > 0 && f.source !== "person"),
           missing: run.facts.filter((f) => !f.value) };
}

/** The run's state in the breadcrumb, while it is live: the one place it is said. */
export function runStatusWord(run: Pick<RunSummary, "status" | "step" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words): string {
  if (run.status === "paused") return m.pbStatusPaused;
  if (run.status === "reading") return m.pbStatusReading;
  if (run.status !== "waiting") return "";
  const kind = stepKind(run, playbook);
  return kind === "checkpoint" ? m.pbStatusReview : kind === "request" ? m.pbStatusWaitsDocs : kind === "ask" ? m.pbStatusWaitsAnswers : "";
}

/** A fact's first source as SourceRef shows it. */
function sourceText(f: RunFact, m: Words): { n: number; text: string; name: string } | null {
  const c = f.citations[0];
  return c ? { n: c.n, text: c.filename + (c.page ? `, ${m.pageShort(c.page)}` : ""), name: m.sourceLabel(c.n, c.filename, c.page) } : null;
}

/** The panel beside a run: the reference list, or one fact's source (from the list, with a way back; or from a card). */
export type RunPanelView = { kind: "list" } | { kind: "source"; fact: string; fromList: boolean };

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

export function RunThread({ run, kase, playbook, words, me, canAnswer, nameOf, panel, onChanged, onPanel, onRestart, onDocumentsChanged }: {
  run: Run; kase: Case; playbook: PlaybookInfo | null; words: PlaybookWords; me?: string;
  /** A contributor of an open case: answers, confirms, pauses (the gateway decides; this only hides). */
  canAnswer: boolean;
  /** A username as the case knows the person (the run records usernames). */
  nameOf: (username: string) => string;
  /** What the panel beside the conversation shows (null: closed). */
  panel: RunPanelView | null;
  onChanged: (run: Run) => void;
  onPanel: (view: RunPanelView | null) => void;
  /** Start the playbook again (a new conversation): after an error. */
  onRestart?: () => void;
  onDocumentsChanged: () => void;
}) {
  const m = useT();
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [run.turns.length, run.status]);
  const title = words.title || playbook?.name || "";
  const reviewAt = run.status === "waiting" ? [...run.turns].reverse().find((t) => t.meta.kind === "checkpoint" && t.step_id === run.step)?.seq : undefined;
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
                            review={t.seq === reviewAt
                              ? <Review run={run} kase={kase} words={words} canAnswer={canAnswer} panel={panel} onPanel={onPanel} onChanged={onChanged} />
                              : null}
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
      <RunComposer run={run} kase={kase} title={title} me={me} canAnswer={canAnswer}
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

function PlaybookTurn({ turn, title, showSpeaker, words, review, quickReply }: {
  turn: RunTurn; title: string; showSpeaker: boolean; words: PlaybookWords;
  /** At review: the cards, under the message's own words. */
  review: ReactNode | null;
  quickReply: (() => Promise<void>) | null;
}) {
  const m = useT();
  const [sending, setSending] = useState(false);
  const meta = turn.meta as { kind?: string; facts?: string[]; found?: number; total?: number; fact?: string; value?: string };
  const label = (id: string) => words.labels[id] ?? id;
  const text = meta.kind === "ask" ? m.runAskTurn(meta.found ?? 0, meta.total ?? 0, (meta.facts ?? []).map(label).join(", "))
    : meta.kind === "checkpoint" ? (review ? null : m.pbReviewIntroNone(meta.found ?? 0, meta.total ?? 0))
    : meta.kind === "changed" ? m.runChanged(label(meta.fact ?? ""), meta.value ?? "")
    : meta.kind === "unplaced" ? (meta.facts ? m.runUnplacedAsk : m.runUnplacedChange)
    : turn.text;
  return (
    <div className="turn-assistant run-turn">
      <Speaking />
      <div className="answer">
        {showSpeaker && <p className="run-speaker">{title}</p>}
        {text && <p>{text}</p>}
        {review}
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

/** The review message's work (handover of 31 October 2026, boards 3 and 4): what was found, one card per
 *  fact that needs the person, *Confirm the facts* (held back while anything is under *Check*), and a link
 *  to every fact. */
function Review({ run, kase, words, canAnswer, panel, onPanel, onChanged }: {
  run: Run; kase: Case; words: PlaybookWords; canAnswer: boolean; panel: RunPanelView | null;
  onPanel: (view: RunPanelView | null) => void; onChanged: (run: Run) => void;
}) {
  const m = useT();
  const why = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { check, missing } = reviewGroups(run);
  const [found, total] = factCounts(run);
  const label = (f: RunFact) => words.labels[f.id] ?? f.id;
  const save = async (f: RunFact, value: string) => {
    setError(null);
    try { onChanged(await setRunFact(kase.id, run.id, f.id, value)); } catch (e) { setError((e as Error).message); }
  };
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try { onChanged(await confirmRun(kase.id, run.id, run.facts.map((f) => ({ id: f.id, confirmed: f.value })))); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const blocked = check.length > 0;
  const n = check.length + missing.length;
  const card = (f: RunFact, group: "check" | "missing") => (
    <FactCard key={f.id} fact={f} label={label(f)} group={group} canAnswer={canAnswer}
              active={panel?.kind === "source" && panel.fact === f.id}
              onSave={(v) => save(f, v)} onSource={() => onPanel({ kind: "source", fact: f.id, fromList: false })} />
  );
  return (
    <div className="run-review">
      <p>{n ? m.pbReviewIntro(found, total, n) : m.pbReviewIntroNone(found, total)}</p>
      {check.length > 0 && <section className="run-group" aria-label={m.pbGroupCheck}><h3 className="run-group-title">{m.pbGroupCheck}</h3>{check.map((f) => card(f, "check"))}</section>}
      {missing.length > 0 && <section className="run-group" aria-label={m.pbGroupMissing}><h3 className="run-group-title">{m.pbGroupMissing}</h3>{missing.map((f) => card(f, "missing"))}</section>}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      <div className="run-review-actions">
        {canAnswer && (
          <>
            {/* disabled but focusable, with its reason (React Aria keeps a disabled button out of the tab order; this one says why) */}
            <Button variant="primary" onPress={() => { if (!blocked) void confirm(); }} isDisabled={busy}
                    aria-disabled={blocked || undefined} data-blocked={blocked || undefined} aria-describedby={blocked ? why : undefined}>
              {busy ? m.saving : m.confirmAll}
            </Button>
            {blocked && <span id={why} className="ui-visually-hidden">{check.length === 1 ? m.pbConfirmBlockedOne(label(check[0])) : m.pbConfirmBlocked}</span>}
          </>
        )}
        <TextButton link className="run-all-facts" onPress={() => onPanel({ kind: "list" })}>{m.pbAllFacts(total)}</TextButton>
      </div>
    </div>
  );
}

/** One fact that needs the person: its label and value, *Adjust* or *Fill in* turning it into a field in place
 *  (Enter keeps it, Esc cancels), and for *Check* the passage with what the check couldn't find, and its source. */
function FactCard({ fact, label, group, canAnswer, active, onSave, onSource }: {
  fact: RunFact; label: string; group: "check" | "missing"; canAnswer: boolean; active: boolean;
  onSave: (value: string) => Promise<void>; onSource: () => void;
}) {
  const m = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.value);
  const [saving, setSaving] = useState(false);
  const field = useRef<HTMLDivElement>(null);
  useEffect(() => { if (editing) { setDraft(fact.value); field.current?.querySelector("textarea")?.focus(); } }, [editing, fact.value]);
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!draft.trim()) return;
      setSaving(true);
      onSave(draft.trim()).finally(() => { setSaving(false); setEditing(false); });
    }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setEditing(false); }
  };
  const src = sourceText(fact, m);
  const quote = fact.citations[0]?.text;
  return (
    <Card compact className="fact-card">
      <div className="fact-card-head">
        <div className="fact-card-main">
          <span className="fact-card-label">{label}</span>
          {editing ? (
            <div ref={field} title={m.pbFieldHint}>
              <TextArea label={m.changeValue(label, fact.value || m.answerPlaceholder)} hideLabel value={draft} onChange={setDraft} onKeyDown={onKey}
                        rows={1} className="playbook-fact-field" isReadOnly={saving} />
            </div>
          ) : fact.value ? <span className="fact-card-value">{fact.value}</span> : <em className="fact-unknown">{m.answerPlaceholder}</em>}
        </div>
        {canAnswer && !editing && (
          <Button variant="quiet" size="small" onPress={() => setEditing(true)}>{group === "check" ? m.pbAdjust : m.pbFill}</Button>
        )}
      </div>
      {group === "check" && quote && <blockquote className="fact-card-quote">{quote}</blockquote>}
      {group === "check" && (
        <div className="fact-card-foot">
          <span className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {m.pbNotInPassage(fact.issues.join(", "))}</span>
          {src && <SourceRef n={src.n} text={src.text} name={src.name} active={active} onPress={onSource} />}
        </div>
      )}
    </Card>
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

function RunComposer({ run, kase, title, me, canAnswer, onChanged, onDocumentsChanged }: {
  run: Run; kase: Case; title: string; me?: string; canAnswer: boolean;
  onChanged: (run: Run) => void; onDocumentsChanged: () => void;
}) {
  const m = useT();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
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
      <ActionMenu className="chip-run" data-status={run.status} aria-label={run.status === "paused" ? m.pbChipPaused(title) : title}
                  menuLabel={m.runMenu} placement="top start" entries={menu} isDisabled={busy}
                  onAction={(id) => { if (id === "cancel") setCancelling(true); else void act(id as "pause" | "resume" | "stop"); }}>
        {run.status === "paused" ? <Pause size={13} aria-hidden /> : <Route size={13} aria-hidden />}
        {run.status === "paused" ? m.pbChipPaused(title) : title}
        <ChevronDown size={13} aria-hidden />
      </ActionMenu>
    ) : (
      <span className="chip-run" data-status={run.status}>
        {run.status === "paused" ? <Pause size={13} aria-hidden /> : <Route size={13} aria-hidden />}
        {run.status === "paused" ? m.pbChipPaused(title) : title}
      </span>
    )
  );
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

// ------------------------------------------------------------------ the panel: every fact, and a fact's source

/** Beside the conversation, in the source panel's place (handover of 31 October 2026, board 5): every fact
 *  in the pack's order with its source, nothing edited here; or one fact's source, with a way back to the
 *  list when it was opened from there. Esc closes it (or goes back), and focus returns to what opened it. */
export function RunPanel({ run, words, view, onView, onClose }: {
  run: Run; words: PlaybookWords; view: RunPanelView;
  onView: (view: RunPanelView) => void; onClose: () => void;
}) {
  const m = useT();
  const panel = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const scroll = useRef(0);
  const listTitle = m.pbListTitle(words.facts_title || m.factsPanel);
  const fact = view.kind === "source" ? run.facts.find((f) => f.id === view.fact) ?? null : null;
  useEffect(() => { panel.current?.focus(); }, []);
  useEffect(() => { if (view.kind === "list" && list.current) list.current.scrollTop = scroll.current; }, [view.kind]);
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Escape" || (e.target as Element | null)?.closest?.("[role=dialog], [role=menu]")) return;
    e.stopPropagation();
    if (view.kind === "source" && view.fromList) onView({ kind: "list" }); else onClose();
  };
  const close = useCallback(onClose, [onClose]);
  const open = (f: RunFact) => { scroll.current = list.current?.scrollTop ?? 0; onView({ kind: "source", fact: f.id, fromList: true }); };
  return (
    <aside id="run-panel" className="source-panel facts-panel" ref={panel} tabIndex={-1} aria-label={view.kind === "list" ? listTitle : words.labels[fact?.id ?? ""] ?? ""}
           onKeyDown={onKeyDown}>
      {view.kind === "source" && view.fromList && (
        <div className="facts-back"><TextButton onPress={() => onView({ kind: "list" })}><ArrowLeft size={14} aria-hidden /> {listTitle}</TextButton></div>
      )}
      <header className="source-panel-head">
        <span className="source-panel-title">
          <span className="source-panel-file">{view.kind === "list" ? listTitle : words.labels[fact?.id ?? ""] ?? fact?.id}</span>
          {fact?.citations[0] && <span className="source-panel-where">{fact.citations[0].filename}{fact.citations[0].page ? `, ${m.pageShort(fact.citations[0].page)}` : ""}</span>}
        </span>
        <span className="composer-space" />
        <IconButton label={m.close} onPress={close}><X size={16} aria-hidden /></IconButton>
      </header>
      <div className="source-panel-body" ref={list}>
        {view.kind === "list" ? (
          <ol className="facts">
            {run.facts.map((f) => <FactRow key={f.id} fact={f} label={words.labels[f.id] ?? f.id} onSource={() => open(f)} />)}
          </ol>
        ) : fact?.citations[0] ? <Passage fact={fact} /> : null}
      </div>
    </aside>
  );
}

function FactRow({ fact, label, onSource }: { fact: RunFact; label: string; onSource: () => void }) {
  const m = useT();
  const value = fact.confirmed ?? fact.value;
  const src = sourceText(fact, m);
  // a value given or changed in the conversation; one only checked (unchanged) keeps its source
  const fromChat = fact.source === "person" && fact.was !== fact.value;
  const confirmed = fact.confirmed !== null && fact.confirmed !== "";
  return (
    <li className="fact" data-confirmed={confirmed || undefined}>
      <span className="fact-label">{label}</span>
      <div className="fact-row">
        {value ? <span className="fact-value">{value}</span> : <em className="fact-value fact-unknown">{m.answerPlaceholder}</em>}
        {confirmed && <Check size={14} className="fact-check" aria-label={m.factConfirmed} />}
      </div>
      {fromChat && fact.at ? <span className="fact-note">{m.pbFromChat(time(fact.at))}</span>
        : src ? <span className="fact-note"><SourceRef n={src.n} text={src.text} name={src.name} onPress={onSource} /></span> : null}
      {fact.issues.length > 0 && fact.source !== "person" && <span className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {m.factCheckThis}</span>}
    </li>
  );
}

function Passage({ fact }: { fact: RunFact }) {
  const first = fact.citations[0];
  const citation: Citation = { text: first.text, source: { document_id: first.document_id, page: first.page, location: first.location } };
  return <SourceCard n={first.n} citation={citation} filename={first.filename} claims={[fact.value]} />;
}
