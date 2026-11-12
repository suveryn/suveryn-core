/**
 * A playbook is a conversation (decision, 30 October 2026; docs/design/playbooks.md, "The chat UI"; boards
 * 52 to 54). Starting one from the composer's *Playbook* menu makes a new conversation in the case,
 * titled with the playbook; it is listed with the case's other conversations and opens here. The
 * playbook speaks as sūveryn (the mark with the route badge, the playbook's title as speaker), people
 * answer in the composer in their own words, and the documents come in through the paperclip. At review the
 * work comes to the playbook's message (handover of 31 October 2026): one card per fact that needs the
 * person (*Check*, *Missing*), changed in place, and *Confirm the facts*; every fact is in a reference list
 * in the panel beside the conversation, nothing edited there. Sources look the same as under an answer.
 *
 * The run's turns are rows the server writes (``turns``); the playbook's own lines carry a ``meta.kind``
 * the thread words in the interface language (``ask``, ``checkpoint``, ``changed``, ``unplaced``, ``already_unknown``, and the
 * events ``paused``, ``resumed``, ``stopped``, ``cancelled``, ``confirmed``), the pack's questions are
 * shown as written. Pause, cancel and stop are on the run's chip in the composer, shown only to those the
 * gateway would allow (it decides; the chip hides what would fail).
 */
import { citedContext } from "../lib/quote";
import {
  ArrowUp, Check, ChevronDown, CircleAlert, CircleX, Download, FileText, Paperclip, Pause, Play, Route, Square, TriangleAlert, X,
} from "lucide-react";
import { useId } from "react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  answerRun, confirmRun, getRun, HttpError, isArchiveUpload, runAction, sayInRun, setRunFact, uploadDocument,
  type Case, type Job, type PlaybookInfo, type Run, type RunFact, type RunStatus, type RunSummary, type RunTurn,
  type Computed,
} from "../api";
import { useWatermark } from "../lib/watermark";
import { lang, locale, useT } from "../i18n";
import {
  entriesOf, entryPath, factGroups, factLabel, groupFound, nextEntry, optionLabel, shownFacts, splitPath, type FactGroup, type PlaybookWords,
} from "../lib/playbooks";
import { ACCEPTED_FILES } from "../lib/formats";
import { failureText } from "../lib/review";
import { dayLabel } from "../lib/conversations";
import { checkJob, LOST_TRACK } from "../lib/uploads";
import { exportRef } from "../lib/marks";
import { EVENTS, eventText, personTurnText, playbookTurnText, type TurnMeta } from "../lib/runTurns";
import {
  ActionMenu, Button, Card, Dialog, IconBadge, IconButton, InlineNotice, SourceRef, TextArea, TextButton, useFilePicker, type MenuEntry,
} from "../ui";
import { AssistantMark } from "./Brand";
import { SourcePanel } from "./Messages";
import type { AssistantTurn } from "../types";

const POLL_MS = 1500;
const LIVE: RunStatus[] = ["reading", "waiting", "paused"];
type Words = ReturnType<typeof useT>;

// ------------------------------------------------------------------ words shared with the case lists

export function statusLabel(status: RunStatus, m: Words): string {
  return { reading: m.runReading, waiting: m.runWaiting, paused: m.runPaused, done: m.runDone, stopped: m.runStopped,
           cancelled: m.runCancelled, failed: m.runFailed }[status] ?? status;
}

/** The step's kind, from the playbook's routine (the server also sends it as ``step_kind``). */
function stepKind(run: Pick<RunSummary, "step" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined): string | null {
  return run.step_kind ?? playbook?.steps?.find((s) => s.id === run.step)?.kind ?? null;
}

/** The step's name, for the chip on a case: the kind in words, since the playbook names its steps for the machine. */
export function stepLabel(run: Pick<RunSummary, "step" | "status" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words): string {
  const kind = stepKind(run, playbook);
  if (run.status === "reading" || kind === "read") return m.stepReading;
  const names: Record<string, string> = { request: m.stepRequest, ask: m.stepAsk, checkpoint: m.stepCheckpoint, produce: m.stepProduce };
  return names[kind ?? ""] ?? "";
}

/** Who a waiting run waits for (board P04, 7): the case's members at the checkpoint, else the person who started it,
 *  "you" when that is the reader, by first name otherwise. */
export function waitsFor(run: Pick<RunSummary, "step" | "step_kind" | "starter">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined,
                         m: Words, me?: string, starterName?: string | null): string {
  if (stepKind(run, playbook) === "checkpoint") return m.waitsForMember;
  if (me && run.starter === me) return m.waitsForYou;
  return starterName ? m.waitsFor(starterName.split(" ")[0]) : m.waitsForMember;
}

/** A playbook's last run in this case, for the line under it in the playbook menu (board P04, 9): "Laatst: vandaag,
 *  klaar · start een nieuw gesprek", or for a run still open "Loopt: wacht op Mieke · opent dat gesprek". */
export function lastRunLine(run: RunSummary, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words, me?: string,
                            starterName?: string | null, now: Date = new Date()): string {
  const low = (s: string) => s.toLocaleLowerCase(locale());
  if (LIVE.includes(run.status)) {
    return m.pbRunningNow(run.status === "waiting" ? waitsFor(run, playbook, m, me, starterName)
      : run.status === "reading" ? m.stepReading : low(m.runPaused));
  }
  return m.pbLastRun(low(dayLabel(run.finished_at ?? run.started_at, now)), low(statusLabel(run.status, m)));
}

/** One line for the chip on a case in the case lists: the playbook's title and what the run waits for ("Akte-intake ·
 *  wacht op Mieke"; board P04, 7). Without ``people``: the step in words, as before. */
export function runChipText(run: RunSummary, playbook: Pick<PlaybookInfo, "steps" | "name" | "text"> | null | undefined, title: string, m: Words, lang?: string,
                            people?: { me?: string; starterName?: string | null }): string {
  const name = (lang && run.title?.[lang]) || run.title?.en || title;
  const what = run.status === "paused" ? m.runPaused
    : run.status === "waiting" && people ? waitsFor(run, playbook, m, people.me, people.starterName) : stepLabel(run, playbook, m);
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

/** The facts a review card is for (handover of 31 October 2026; board P01): *Check*, a value the check couldn't find
 *  literally in its passage, or one sūveryn worked out, that nobody has checked since; *Missing*, a fact without a value,
 *  a list without entries among them. A list that has entries isn't missing, nor is a field an entry lacks: one more entry
 *  is added in the panel, a field corrected in words. */
export function reviewGroups(run: Pick<Run, "facts">): { check: RunFact[]; missing: RunFact[] } {
  const facts = shownFacts(run.facts);
  return { check: facts.filter((f) => f.value && (f.issues.length > 0 || !!f.needs) && f.source !== "person"),
           missing: facts.filter((f) => !f.value && splitPath(f.id).index === null) };
}

/** The run's state in the breadcrumb, while it is live: the one place it is said. */
export function runStatusWord(run: Pick<RunSummary, "status" | "step" | "step_kind">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words): string {
  if (run.status === "paused") return m.pbStatusPaused;
  if (run.status === "reading") return m.pbStatusReading;
  if (run.status !== "waiting") return "";
  const kind = stepKind(run, playbook);
  return kind === "checkpoint" ? m.pbStatusReview : kind === "request" ? m.pbStatusWaitsDocs : kind === "ask" ? m.pbStatusWaitsAnswers : "";
}

/** Why a fact is under *Check*, in words: a value that gives no date or amount as such, or what the passage doesn't say. */
function checkReason(f: RunFact, m: Words): string {
  if (f.needs === "computed") return m.pbComputedCheck;
  if (f.needs === "not_a_date") return m.pbNotADate;
  if (f.needs === "not_an_amount") return m.pbNotAnAmount;
  if (f.needs === "not_a_number") return m.pbNotANumber;
  if (f.needs === "approximate") return m.pbApproximate;
  if (f.needs === "invalid_number") return m.pbInvalidNumber;
  return m.pbNotInPassage(f.issues.join(", "));
}

/** A fact's first source as SourceRef shows it. */
function sourceText(f: RunFact, m: Words): { n: number; text: string; name: string } | null {
  const c = f.citations[0];
  return c ? { n: c.n, text: c.filename + (c.page ? `, ${m.pageShort(c.page)}` : ""), name: m.sourceLabel(c.n, c.filename, c.page) } : null;
}

/** The panel beside a run: the reference list, or one fact's source (from the list, with a way back; or from a card). */
export type RunPanelView = { kind: "list"; from?: string } | { kind: "source"; fact: string; fromList: boolean };

/** How many facts have a value, of how many: a list is one fact, found when it has an entry (board P01: "12 of 13"). */
export const factCounts = (run: Pick<Run, "facts"> & { playbook?: Pick<PlaybookInfo, "lists"> | null }) => {
  const groups = factGroups(run.facts, run.playbook?.lists ?? {});
  return [groups.filter(groupFound).length, groups.length] as const;
};

/** How a value was worked out, in words: "Berekend: 12 oktober 2026 plus vier maanden.", "… plus tien werkdagen
 *  (maandag tot vrijdag, Belgische feestdagen).", "Berekend: 10 % van 385.000,00." */
export function computedHow(c: Computed, m: Words): string {
  if (c.kind === "share") {
    const number = (v: string) => new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 }).format(Number(v));
    return m.pbComputedShare(number(c.percent), number(c.of));
  }
  const base = new Date(`${c.base}T12:00:00`).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" });
  const calendar = c.calendar ? (c.calendar[lang()] ?? c.calendar.en ?? "") : "";
  return m.pbComputedHow(base, m.pbTerm(c.amount, c.unit), c.direction === "before", calendar);
}

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
  // the question still standing: the step's last ask, also after "That couldn't be placed" (finding 6)
  const openAsk = run.status === "waiting" ? [...run.turns].reverse().find((t) => t.meta.kind === "ask" && t.step_id === run.step)?.seq : undefined;
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
            ? <PersonTurn key={t.seq} turn={t} nameOf={nameOf} words={words} />
            : <PlaybookTurn key={t.seq} turn={t} title={title} showSpeaker={speaker(i)} words={words}
                            // a choice the playbook asks about: its options as buttons (format 3, "Choices")
                            choices={t.meta.kind === "ask" && canAnswer && run.status === "waiting" && t.seq === openAsk
                              ? ((t.meta.facts as string[] | undefined) ?? []).filter((f) => playbook?.choices?.[f]).map((f) => ({
                                  fact: f, label: factLabel(words, f),
                                  options: playbook!.choices![f].map((o) => ({ id: o, label: optionLabel(words, f, o),
                                    send: () => answerRun(kase.id, run.id, run.step ?? "", { facts: { [f]: o } }).then(onChanged) })) }))
                              : []}
                            review={t.seq === reviewAt
                              ? <Review run={run} kase={kase} words={words} lists={playbook?.lists ?? {}} steps={playbook?.steps ?? []} canAnswer={canAnswer} me={me} panel={panel} onPanel={onPanel} onChanged={onChanged} />
                              : null}
                            quickReply={t.meta.kind === "ask" && canAnswer && run.status === "waiting" && t.seq === openAsk
                              ? { label: m.answerPlaceholder, send: () => sayInRun(kase.id, run.id, { unknown: true }).then(onChanged) }
                              // the request always asks; the documents may already be in the case (question 1)
                              : canAnswer && run.status === "waiting" && t.step_id === run.step && stepKind(run, playbook) === "request"
                                && i === run.turns.length - 1 && t.role === "playbook" && t.meta.kind === "request"
                              ? { label: m.runUseCaseDocuments, send: () => sayInRun(kase.id, run.id, { case_documents: true }).then(onChanged) }
                              : null}
                            // a request the playbook can do without (the title deed, the certificates): "There is none"
                            noneReply={canAnswer && run.status === "waiting" && t.step_id === run.step && stepKind(run, playbook) === "request"
                                && i === run.turns.length - 1 && t.role === "playbook" && t.meta.kind === "request"
                                && playbook?.steps?.find((s) => s.id === run.step)?.allow_none
                              ? { label: m.runNoDocument, send: () => answerRun(kase.id, run.id, run.step ?? "", { none: true }).then(onChanged) }
                              : null} />))}
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

const isEvent = (t: RunTurn) => t.role === "playbook" && typeof t.meta.kind === "string" && EVENTS.has(t.meta.kind);

/** The brand mark with the route badge: a playbook speaking (badge-icon, system). */
function Speaking() {
  return <IconBadge badge={<Route />} host="icon" tone="system"><AssistantMark /></IconBadge>;
}

function PlaybookTurn({ turn, title, showSpeaker, words, review, quickReply, noneReply = null, choices = [] }: {
  turn: RunTurn; title: string; showSpeaker: boolean; words: PlaybookWords;
  /** At review: the cards, under the message's own words. */
  review: ReactNode | null;
  quickReply: { label: string; send: () => Promise<void> } | null;
  /** At a request a playbook can do without: "There is none", beside the quick reply. */
  noneReply?: { label: string; send: () => Promise<void> } | null;
  /** At an ask about a choice: the fact's options as buttons. */
  choices?: { fact: string; label: string; options: { id: string; label: string; send: () => Promise<void> }[] }[];
}) {
  const m = useT();
  const [sending, setSending] = useState(false);
  const meta = { step: turn.step_id ?? undefined, ...(turn.meta as TurnMeta) };  // a request's step is the turn's
  // the meaning in the reader's words (lib/runTurns.ts); a turn stored before 12 November keeps its text
  const text = meta.kind === "checkpoint" && review ? null : meta.kind ? playbookTurnText(meta, m, words) : turn.text;
  return (
    <div className="turn-assistant run-turn">
      <Speaking />
      <div className="answer">
        {showSpeaker && <p className="run-speaker">{title}</p>}
        {text && <p>{text}</p>}
        {review}
        {choices.map((c) => (
          <div key={c.fact} className="run-quick run-choice" role="group" aria-label={c.label}>
            {c.options.map((o) => (
              <Button key={o.id} variant="secondary" size="small" isDisabled={sending}
                      onPress={() => { setSending(true); o.send().finally(() => setSending(false)); }}>{o.label}</Button>
            ))}
          </div>
        ))}
        {(quickReply || noneReply) && (
          <div className="run-quick">
            {[quickReply, noneReply].filter((r): r is { label: string; send: () => Promise<void> } => r !== null).map((r) => (
              <Button key={r.label} variant="secondary" size="small" isDisabled={sending}
                      onPress={() => { setSending(true); r.send().finally(() => setSending(false)); }}>{r.label}</Button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** The review message's work (handover of 31 October 2026, boards 3 and 4): what was found, one card per
 *  fact that needs the person, *Confirm the facts* (held back while anything is under *Check*), and a link
 *  to every fact. */
function Review({ run, kase, words, lists, steps, canAnswer, me, panel, onPanel, onChanged }: {
  run: Run; kase: Case; words: PlaybookWords; canAnswer: boolean; me?: string; panel: RunPanelView | null;
  /** Format 3: the playbook's list facts and their entries' fields, so an entry can be added here. */
  lists: Record<string, string[]>;
  /** The routine's steps, for the order of the checks. */
  steps: { id: string; kind: string; by?: string }[];
  onPanel: (view: RunPanelView | null) => void; onChanged: (run: Run) => void;
}) {
  const m = useT();
  const why = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { check, missing } = reviewGroups(run);
  const [found, total] = factCounts(run);
  const label = (f: RunFact) => factLabel(words, f.id);
  const save = async (f: RunFact, value: string) => {
    setError(null);
    try { onChanged(await setRunFact(kase.id, run.id, f.id, value)); } catch (e) { setError((e as Error).message); }
  };
  // an entry a person adds to a list (format 3): one version per value given, as a correction is
  const add = async (list: string, values: Record<string, string>) => {
    setError(null);
    const index = nextEntry(run.facts, list);
    try {
      let fresh = run;
      for (const [field, value] of Object.entries(values)) {
        if (value.trim()) fresh = await setRunFact(kase.id, run.id, entryPath(list, index, field || null), value.trim());
      }
      onChanged(fresh);
    } catch (e) { setError((e as Error).message); }
  };
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try { onChanged(await confirmRun(kase.id, run.id, shownFacts(run.facts).map((f) => ({ id: f.id, confirmed: f.value })), run.facts_seq)); }
    catch (e) {
      setError((e as Error).message);
      // refused because a colleague changed a fact meanwhile: show what stands now, the person confirms again
      if (e instanceof HttpError && e.status === 409) getRun(kase.id, run.id).then(onChanged).catch(() => undefined);
    } finally { setBusy(false); }
  };
  const blocked = check.length > 0;
  // who confirms: anyone who contributes, or, when the checkpoint says so, the case manager (the notary); others prepare and correct
  const managerOnly = steps.find((s) => s.id === run.step)?.by === "manager";
  const canConfirm = canAnswer && (!managerOnly || kase.manager === me);
  const n = check.length + missing.length;
  const card = (f: RunFact, group: "check" | "missing") => f.id in lists ? (
    <AddEntryCard key={f.id} list={f.id} fields={lists[f.id]} count={0} words={words} canAnswer={canAnswer} onAdd={(v) => add(f.id, v)} />
  ) : (
    <FactCard key={f.id} fact={f} label={label(f)} group={group} canAnswer={canAnswer}
              active={panel?.kind === "source" && panel.fact === f.id}
              onSave={(v) => save(f, v)} onSource={() => onPanel({ kind: "source", fact: f.id, fromList: false })} />
  );
  // the checks that fail (format 3; board P01), in the routine's order: a point for the notary, never a block. Those that
  // hold, or can't be worked out yet, are in the panel.
  const checks = steps.filter((s) => s.kind === "check" && run.checks?.[s.id]?.status === "fails").map((s) => ({ id: s.id, ...run.checks![s.id] }));
  return (
    <div className="run-review">
      <p>{n ? m.pbReviewIntro(found, total, n) : m.pbReviewIntroNone(found, total)}</p>
      {checks.length > 0 && (
        <section className="run-group" aria-label={m.pbGroupChecks}>
          <h3 className="run-group-title">{m.pbGroupChecks}</h3>
          <ul className="run-checks">
            {checks.map((c) => (
              <li key={c.id} className="run-check" data-status={c.status}>
                {c.status === "holds" ? <Check size={14} aria-hidden /> : <TriangleAlert size={14} aria-hidden />}
                <span>
                  <span className="run-check-text">{words.checks?.[c.id] ?? c.rule}</span>
                  <span className="run-check-note">{c.status === "holds" ? m.pbCheckHolds : c.status === "fails" ? m.pbCheckFails(c.left, c.right)
                    : m.pbCheckOpen(c.missing.map((p) => factLabel(words, p)).join(", "))}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {check.length > 0 && <section className="run-group" aria-label={m.pbGroupCheck}><h3 className="run-group-title">{m.pbGroupCheck}</h3>{check.map((f) => card(f, "check"))}</section>}
      {missing.length > 0 && <section className="run-group" aria-label={m.pbGroupMissing}><h3 className="run-group-title">{m.pbGroupMissing}</h3>{missing.map((f) => card(f, "missing"))}</section>}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      <div className="run-review-actions">
        {canAnswer && !canConfirm && <span className="caption run-confirm-note">{m.pbManagerConfirms}</span>}
        {canConfirm && (
          <>
            {/* disabled but focusable, with its reason (React Aria keeps a disabled button out of the tab order; this one says why) */}
            <Button variant="primary" onPress={() => { if (!blocked) void confirm(); }} isDisabled={busy}
                    aria-disabled={blocked || undefined} data-blocked={blocked || undefined} aria-describedby={blocked ? why : undefined}>
              {busy ? m.saving : m.confirmAll}
            </Button>
            {blocked && <span id={why} className="ui-visually-hidden">{check.length === 1 ? m.pbConfirmBlockedOne(label(check[0])) : m.pbConfirmBlocked}</span>}
          </>
        )}
        {/* ink, underlined: orange is the main action only (board P01) */}
        <TextButton className="run-all-facts" onPress={() => onPanel({ kind: "list" })}>{m.pbAllFacts(total)}</TextButton>
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
  // the passage around what it cites: for a worked-out date, the term as written (board P01)
  const quote = fact.citations[0]?.text ? citedContext(fact.citations[0].text, fact.computed?.written ?? fact.value) : undefined;
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
          <Button variant="secondary" size="small" onPress={() => setEditing(true)}>{group === "check" ? m.pbAdjust : m.pbFill}</Button>
        )}
      </div>
      {group === "check" && quote && (
        <blockquote className="fact-card-quote" data-context={quote.cited !== undefined || undefined}>
          {quote.cited !== undefined
            ? <><span className="quote-context">{quote.before}</span><span className="quote-cited">{quote.cited}</span><span className="quote-context">{quote.after}</span></>
            : quote.text}
        </blockquote>
      )}
      {group === "check" && (
        <div className="fact-card-foot">
          {fact.computed ? <span className="fact-note fact-computed">{computedHow(fact.computed, m)}</span>
            : <span className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {checkReason(fact, m)}</span>}
          {src && <SourceRef n={src.n} text={src.text} name={src.name} active={active} onPress={onSource} />}
        </div>
      )}
    </Card>
  );
}

/** A list the documents named no entries of, or one more entry for a list that has some (format 3): *Add* opens one
 *  field per value of the entry (a record's fields, or the one value), *Keep* saves what was filled in. */
function AddEntryCard({ list, fields, count, words, canAnswer, onAdd, inline = false }: {
  list: string; fields: string[]; count: number; words: PlaybookWords; canAnswer: boolean; onAdd: (values: Record<string, string>) => Promise<void>;
  /** At the end of the list's block in the panel (board P03): only *Add* and, once pressed, the fields. */
  inline?: boolean;
}) {
  const m = useT();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const keys = fields.length ? fields : [""];
  const fieldLabel = (field: string) => field ? (words.labels[`${list}.${field}`] ?? field) : (words.labels[list] ?? list);
  const keep = () => {
    if (!Object.values(draft).some((v) => v.trim())) { setOpen(false); return; }
    setSaving(true);
    onAdd(draft).finally(() => { setSaving(false); setOpen(false); setDraft({}); });
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); keep(); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); setDraft({}); }
  };
  const fieldsOpen = open && (
    <div className="fact-card-entry-fields" title={m.pbFieldHint}>
      {keys.map((field) => (
        <TextArea key={field} label={fieldLabel(field)} value={draft[field] ?? ""} onChange={(v) => setDraft({ ...draft, [field]: v })}
                  onKeyDown={onKey} rows={1} className="playbook-fact-field" isReadOnly={saving} />
      ))}
      <div className="run-quick">
        <Button variant="secondary" size="small" onPress={keep} isDisabled={saving}>{saving ? m.saving : m.pbKeepEntry}</Button>
        <Button variant="quiet" size="small" onPress={() => { setOpen(false); setDraft({}); }} isDisabled={saving}>{m.cancel}</Button>
      </div>
    </div>
  );
  if (inline) {
    return (
      <div className="fact-list-add">
        {!open && <Button variant="secondary" size="small" onPress={() => setOpen(true)}>{m.pbAddEntry}</Button>}
        {fieldsOpen}
      </div>
    );
  }
  return (
    <Card compact className="fact-card fact-card-entry">
      <div className="fact-card-head">
        <div className="fact-card-main">
          <span className="fact-card-label">{words.labels[list] ?? list}</span>
          {!open && (count ? <span className="fact-card-value">{m.pbEntries(count)}</span> : <em className="fact-unknown">{m.pbNoEntries}</em>)}
        </div>
        {canAnswer && !open && <Button variant="secondary" size="small" onPress={() => setOpen(true)}>{m.pbAddEntry}</Button>}
      </div>
      {fieldsOpen}
    </Card>
  );
}

function PersonTurn({ turn, nameOf, words }: { turn: RunTurn; nameOf: (u: string) => string; words: PlaybookWords }) {
  const m = useT();
  const said = personTurnText(turn, m, words);
  const attachments = (turn.meta.attachments as { documentId: string; filename: string }[] | undefined) ?? [];
  return (
    <div className="turn-user">
      {attachments.length > 0 && (
        <div className="attachments">
          {attachments.map((a) => <span key={a.documentId} className="chip-attachment"><FileText size={13} aria-hidden /> {a.filename}</span>)}
        </div>
      )}
      {said && <div className="bubble">{said}</div>}
      <span className="caption">{nameOf(turn.by)} · {dayAndTime(turn.at)}</span>
    </div>
  );
}

/** Paused, resumed, stopped, cancelled, confirmed: a centred line with its icon; "Confirmed" in teal (a system status). */
function EventLine({ turn, nameOf }: { turn: RunTurn; nameOf: (u: string) => string }) {
  const m = useT();
  const who = nameOf(turn.by), at = dayAndTime(turn.at);
  const kind = turn.meta.kind as string;
  const icon = kind === "confirmed" ? <Check size={13} /> : kind === "paused" ? <Pause size={13} />
    : kind === "resumed" ? <Play size={13} /> : kind === "stopped" ? <Square size={13} /> : <CircleX size={13} />;
  const text = eventText(turn.meta as TurnMeta, who, at, m);
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
      facts: shownFacts(run.facts).map((f) => ({ label: factLabel(words, f.id), value: f.confirmed ?? f.value,
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
  // Documents read into the case, waiting to go with the person's turn: a line and its documents are one turn
  // (VM regression e0f2e26, finding 2: sent apart they were two, and each moved the run on).
  const [ready, setReady] = useState<{ id: string; filename: string }[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const live = LIVE.includes(run.status);
  const mayEnd = live && (run.starter === me || kase.manager === me);
  const waiting = run.status === "waiting";
  // While sūveryn reads, the field stays open (board P04, 3): what is sent then is held, and goes as the person's turn
  // when the playbook next waits for a person.
  const reading = run.status === "reading";
  const [held, setHeld] = useState<string | null>(null);

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
    const done: { id: string; filename: string }[] = [];
    try {
      const jobs: Job[] = [];
      for (const f of files) {
        const r = await uploadDocument(f, undefined, kase.id);
        jobs.push(...(isArchiveUpload(r) ? r.jobs : [r]));
      }
      const lost: string[] = [];
      for (let job of jobs) {
        while (job.status === "queued" || job.status === "processing") {
          await new Promise((ok) => window.setTimeout(ok, 1000));
          const c = await checkJob(job.id);
          if (c === "lost") { lost.push(job.filename); break; }  // a restart forgot it (lib/uploads.ts)
          job = c;
        }
        if (job.document_id && (job.status === "ready" || job.status === "needs_review")) done.push({ id: job.document_id, filename: job.filename });
      }
      if (lost.length) setError(lost.map((f) => `${f}: ${failureText(m, LOST_TRACK)}`).join(" "));
    } catch (e) { setError((e as Error).message); }
    setUploading([]);
    onDocumentsChanged();
    setReady((r) => [...r, ...done.filter((d) => !r.some((x) => x.id === d.id))]);
  };
  const picker = useFilePicker(ACCEPTED_FILES, true, (files) => void upload(files));
  useEffect(() => {
    if (!waiting || held === null) return;
    setHeld(null);
    void say({ text: held });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the run starts waiting with something held
  }, [waiting, held]);
  const canSend = (waiting || reading) && !busy && uploading.length === 0 && (!!text.trim() || (waiting && ready.length > 0));
  const send = () => {
    if (!canSend) return;
    if (reading) { setHeld((h) => (h ? `${h}\n` : "") + text.trim()); setText(""); return; }
    void say({ text: text.trim(), ...(ready.length ? { documents: ready.map((d) => d.id) } : {}) }).then(() => setReady([]));
  };
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
      {(uploading.length > 0 || ready.length > 0) && (
        <ul className="attachment-cards">
          {ready.map((d) => (
            <li key={d.id} className="chip-attachment"><FileText size={13} aria-hidden /> {d.filename}
              <IconButton size="small" label={m.removeFile(d.filename)} onPress={() => setReady((r) => r.filter((x) => x.id !== d.id))}>
                <X size={12} aria-hidden />
              </IconButton>
            </li>
          ))}
          {uploading.map((n) => <li key={n} className="chip-attachment"><Paperclip size={13} aria-hidden /> {m.uploadingFile(n)}</li>)}
        </ul>
      )}
      <div className="composer">
        <TextArea label={title} hideLabel value={text} onChange={setText} onKeyDown={onKey} isReadOnly={!waiting && !reading}
                  placeholder={waiting ? m.runAnswerPlaceholder : reading ? m.runTypeAhead : run.status === "paused" ? m.runPausedPlaceholder(title) : ""} className="composer-field" />
        <div className="composer-tools">
          {picker.input}
          <IconButton size="small" label={m.addDocuments} onPress={() => picker.open()} isDisabled={!waiting || busy || uploading.length > 0}>
            <Paperclip size={16} aria-hidden />
          </IconButton>
          {chip}
          <span className="composer-space" />
          <Button variant="plain" className="send-button" onPress={send} isDisabled={!canSend} aria-label={m.send}
                  data-empty={(waiting || reading) && !busy && !text.trim() ? true : undefined}>
            <ArrowUp size={16} strokeWidth={2.2} aria-hidden />
          </Button>
        </div>
      </div>
      {held && <p className="composer-hint caption run-held" role="status"><span className="run-held-text">{held}</span> {m.runHeld(title)}</p>}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
      {/* A form whose main action is itself a cancel: the way out says "Keep the run"; the focus starts in
          the reason, where Enter makes a new line and doesn't submit. */}
      <Dialog isOpen={cancelling} onClose={() => setCancelling(false)} kind="form" risky title={m.cancelRun} busy={busy}
              cancel={{ label: m.keepRun }} primary={{ label: m.cancelRunConfirm, onPress: () => void act("cancel"), busyLabel: m.cancelling }}>
        <p>{m.cancelRunExplain}</p>
        <TextArea label={m.cancelReason} value={reason} onChange={setReason} rows={2} className="ui-field playbook-reason" />
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ the panel: every fact, and a fact's source

/** Beside the conversation, in the source panel's place (handover of 31 October 2026, board P03): every fact in the
 *  pack's order with its source, a list as one block (its entries on one line, their other fields under it, dimmed,
 *  and *Add* for one more), then the checks with what each found. A fact's source opens the conversation's own source
 *  panel (``RunSourcePanel``; board P02). Esc closes it, and focus returns to what opened it. */
export function RunPanel({ run, words, view, lists = run.playbook?.lists ?? {}, steps = run.playbook?.steps ?? [], kase = null, canAnswer = false,
                          onChanged, onView, onClose }: {
  run: Run; words: PlaybookWords; view: RunPanelView;
  /** The playbook's lists and their entries' fields; its steps, for the checks' order. */
  lists?: Record<string, string[]>; steps?: { id: string; kind: string }[];
  /** Adding an entry (board P03): the case, and whether the reader may. */
  kase?: Pick<Case, "id"> | null; canAnswer?: boolean; onChanged?: (run: Run) => void;
  onView: (view: RunPanelView) => void; onClose: () => void;
}) {
  const m = useT();
  const panel = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const listTitle = m.pbListTitle(words.facts_title || m.factsPanel);
  const [error, setError] = useState<string | null>(null);
  // Focus follows the view (VM regression e0f2e26, finding 4): the panel when it opens; back from a source, the row it came from.
  useEffect(() => {
    const back = view.kind === "list" && view.from && panel.current?.querySelector<HTMLElement>(`[data-fact="${view.from}"] .ui-source-ref`);
    if (back) back.focus(); else panel.current?.focus();
  }, [view]);
  // Esc while the panel is open, wherever the focus is (not in a dialog, a menu or a field of its own)
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || (e.target as Element | null)?.closest?.("[role=dialog], [role=menu], [role=listbox], textarea, input")) return;
      e.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  const open = (f: RunFact) => onView({ kind: "source", fact: f.id, fromList: true });
  const add = async (listId: string, values: Record<string, string>) => {
    if (!kase || !onChanged) return;
    setError(null);
    const index = nextEntry(run.facts, listId);
    try {
      let fresh = run;
      for (const [field, value] of Object.entries(values)) {
        if (value.trim()) fresh = await setRunFact(kase.id, run.id, entryPath(listId, index, field || null), value.trim());
      }
      onChanged(fresh);
    } catch (e) { setError((e as Error).message); }
  };
  const mayAdd = canAnswer && !!kase && run.status === "waiting";
  const checks = steps.filter((st) => st.kind === "check" && run.checks?.[st.id]).map((st) => ({ id: st.id, ...run.checks![st.id] }));
  return (
    <aside id="run-panel" className="source-panel facts-panel" ref={panel} tabIndex={-1} aria-label={listTitle}>
      <header className="source-panel-head">
        <span className="source-panel-title"><span className="source-panel-file">{listTitle}</span></span>
        <span className="composer-space" />
        <IconButton label={m.close} onPress={onClose}><X size={16} aria-hidden /></IconButton>
      </header>
      <div className="source-panel-body" ref={list}>
        <ol className="facts">
          {factGroups(run.facts, lists).map((g) => g.list
            ? <ListBlock key={g.id} group={g} fields={lists[g.id] ?? []} words={words} canAdd={mayAdd} onSource={open} onAdd={(v) => add(g.id, v)} />
            : <FactRow key={g.id} fact={g.facts[0]} label={factLabel(words, g.id)} onSource={() => open(g.facts[0])} />)}
        </ol>
        {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert>{error}</InlineNotice>}
        {checks.length > 0 && (
          <section className="run-group facts-checks" aria-label={m.pbGroupChecks}>
            <h3 className="run-group-title">{m.pbGroupChecks}</h3>
            <ul className="run-checks">
              {checks.map((c) => (
                <li key={c.id} className="run-check" data-status={c.status}>
                  {c.status === "holds" ? <Check size={14} aria-hidden /> : <TriangleAlert size={14} aria-hidden />}
                  <span>
                    <span className="run-check-text">{words.checks?.[c.id] ?? c.rule}</span>
                    <span className="run-check-note">{c.status === "holds" ? m.pbCheckHolds : c.status === "fails" ? m.pbCheckFails(c.left, c.right)
                      : m.pbCheckOpen(c.missing.map((x) => factLabel(words, x)).join(", "))}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
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
    <li className="fact" data-fact={fact.id} data-confirmed={confirmed || undefined}>
      <span className="fact-label">{label}</span>
      <div className="fact-row">
        {value ? <span className="fact-value">{value}</span> : <em className="fact-value fact-unknown">{m.answerPlaceholder}</em>}
        {confirmed && <Check size={14} className="fact-check" aria-label={m.factConfirmed} />}
      </div>
      {fromChat && fact.at ? <span className="fact-note">{m.pbFromChat(time(fact.at))}</span>
        : src ? <span className="fact-note"><SourceRef n={src.n} text={src.text} name={src.name} onPress={onSource} /></span> : null}
      {(fact.issues.length > 0 || fact.needs) && fact.source !== "person" && !confirmed && (
        <span className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {fact.needs ? checkReason(fact, m) : m.factCheckThis}</span>)}
    </li>
  );
}

/** A list as one block (board P03): "Verkoper(s)", then "Jan Van Damme en Els Peeters" on one line, its source, each entry's
 *  other fields under it, dimmed, when they are known; *Add* at the end for another entry. */
function ListBlock({ group, fields, words, canAdd, onSource, onAdd }: {
  group: FactGroup<RunFact>; fields: string[]; words: PlaybookWords; canAdd: boolean;
  onSource: (f: RunFact) => void; onAdd: (values: Record<string, string>) => Promise<void>;
}) {
  const m = useT();
  const entries = entriesOf(group);
  const [head, ...rest] = fields.length ? fields : [""];
  const shown = (f: RunFact | undefined) => (f ? f.confirmed ?? f.value : "");
  // the entry's name: its first field, else the first value it has
  const nameOf = (values: Record<string, RunFact>) => shown(values[head]) || Object.values(values).map(shown).find(Boolean) || m.answerPlaceholder;
  const names = new Intl.ListFormat(locale(), { type: "conjunction" }).format(entries.map((e) => nameOf(e.values)));
  const first = entries.flatMap((e) => Object.values(e.values)).find((f) => f.citations.length > 0);
  const src = first ? sourceText(first, m) : null;
  const flagged = group.facts.filter((f) => (f.issues.length > 0 || f.needs) && f.source !== "person" && !(f.confirmed ?? ""));
  return (
    <li className="fact fact-list" data-fact={group.id}>
      <span className="fact-label">{words.labels[group.id] ?? group.id}</span>
      <div className="fact-row">
        {entries.length ? <span className="fact-value">{names}</span> : <em className="fact-value fact-unknown">{m.pbNoEntries}</em>}
      </div>
      {src && first && <span className="fact-note"><SourceRef n={src.n} text={src.text} name={src.name} onPress={() => onSource(first)} /></span>}
      {entries.map((e) => {
        const more = rest.map((f) => shown(e.values[f])).filter(Boolean);
        return more.length > 0 && <span key={e.index} className="fact-note fact-entry-more">{nameOf(e.values)} · {more.join(" · ")}</span>;
      })}
      {flagged.map((f) => (
        <span key={f.id} className="fact-note fact-issue"><TriangleAlert size={12} aria-hidden /> {factLabel(words, f.id)}: {f.needs ? checkReason(f, m) : m.factCheckThis}</span>
      ))}
      {canAdd && <AddEntryCard list={group.id} fields={fields} count={entries.length} words={words} canAnswer onAdd={onAdd} inline />}
    </li>
  );
}

/** A fact's source in the conversation's own source panel (board P02, agreed on 31 October): the file and page, "1 of 1"
 *  with its arrows, the passage with the cited words marked, what the check found, how a date was worked out, and
 *  *Open document at p. 4* with *Copy passage*. Closing goes back to the list when it was opened from there. */
export function RunSourcePanel({ run, fact: factId, fromList, caseRef, present, caseId, onView, onClose }: {
  run: Run; fact: string; fromList: boolean; caseRef: string | null;
  present?: ReadonlySet<string>; caseId?: string | null;
  onView: (view: RunPanelView) => void; onClose: () => void;
}) {
  const m = useT();
  const [n, setN] = useState(1);
  const fact = run.facts.find((f) => f.id === factId);
  if (!fact || fact.citations.length === 0) return null;
  const turn = factTurn(fact);
  const filenames = new Map(fact.citations.map((c) => [c.document_id, c.filename]));
  const verdict = fact.computed ? { ok: false, text: fact.computed.kind === "share" ? m.pbAmountNotInPassage : m.pbDateNotInPassage }
    : fact.needs ? { ok: false, text: checkReason(fact, m) } : undefined;
  const back = () => (fromList ? onView({ kind: "list", from: factId }) : onClose());
  return (
    <SourcePanel turn={turn} open={{ n, occ: null }} filenames={filenames} caseRef={caseRef} present={present} caseId={caseId}
                 verdict={verdict} note={fact.computed ? computedHow(fact.computed, m) : undefined} countAlways
                 onSource={(o) => setN(o.n)} onClose={back} />
  );
}

/** A fact as an answer the source panel can show: what it cites (the term as written, for a worked-out date) with a
 *  marker per source, the check's findings as the answer's, and the server's marking of each passage. */
function factTurn(fact: RunFact): AssistantTurn {
  const cited = fact.computed?.written ?? fact.confirmed ?? fact.value;
  return {
    id: `fact-${fact.id}`, role: "assistant", status: "done", grounded: true,
    text: `${cited} ${fact.citations.map((_, i) => `[${i + 1}]`).join("")}`,
    citations: fact.citations.map((c) => ({ text: c.text, source: { document_id: c.document_id, page: c.page, location: c.location }, context: c.context })),
    citationIssues: fact.computed ? [] : fact.issues.map((item) => ({ marker: 0, n: 1, item, found_in: [], written_as: null })),
    supportSpans: fact.citations.map((c, i) => ({ marker: i, n: i + 1, ranges: c.ranges ?? [], facts: c.facts ?? [], how: "words" as const })),
  };
}
