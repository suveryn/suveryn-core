/**
 * A playbook at work in a case (suveryn-tracker#51, docs/design/playbooks.md, "The routine"). The view
 * takes the conversation's place, like Usage. A run is a conversation with a routine: the playbook asks
 * for documents, reads them, asks about what it couldn't find, waits at the checkpoint for a person,
 * and writes the summary. The banner says where the run is and what it waits for; the thread shows the
 * playbook's questions and the people's answers; the composer answers the step the run is on; the
 * panel beside it lists the facts with their status and the product when done. Pause, stop and cancel
 * are in the menu, shown only to those the gateway would allow (it decides; the view hides what would
 * fail). A reader follows; a contributor answers and confirms. Earlier runs are listed under the current one.
 */
import {
  AlertCircle, AlertTriangle, ArrowLeft, ArrowUp, Check, ClipboardList, Download, FileText, Loader2, MoreHorizontal, Paperclip, Pause, Play,
  Square, XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerRun, casePlaybooks, confirmRun, getRun, listRuns, runAction, startRun, uploadDocument,
  type Case, type Citation, type PlaybookInfo, type Run, type RunFact, type RunStatus, type RunSummary, type RunTurn,
} from "../api";
import { useWatermark } from "../lib/watermark";
import { lang, locale, useLang, useT } from "../i18n";
import { playbookWords, stepQuestion, type PlaybookWords } from "../lib/playbooks";
import { dayLabel } from "../lib/conversations";
import { exportRef } from "../lib/marks";
import { intakeToWord, saveBlob } from "../lib/office";
import { ActionMenu, Button, Dialog, FileButton, InlineNotice, TextArea, TextButton, type MenuEntry } from "../ui";
import { AssistantMark } from "./Brand";
import { SourceCard } from "./Messages";

const POLL_MS = 1500;
const UPLOAD_TYPES = [".pdf", ".docx", ".xlsx", ".md", ".csv", ".zip"];

type Words = ReturnType<typeof useT>;

export function PlaybookView({ kase, canRun, me, documents, onBack, onDocumentsChanged, nameOf = (u) => u }: {
  kase: Case; canRun: boolean; documents: number; onBack: () => void; onDocumentsChanged: () => void;
  /** The signed-in person's id: with the case's manager, who may stop or cancel (the gateway decides; the view only hides). */
  me?: string;
  /** A username as the case knows the person: the run records the username (VM regression, finding 13). */
  nameOf?: (username: string) => string;
}) {
  const m = useT();
  const language = useLang();
  const [playbooks, setPlaybooks] = useState<PlaybookInfo[] | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [current, setCurrent] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const refreshRuns = useCallback(async () => {
    try {
      const list = await listRuns(kase.id);
      setRuns(list);
      return list;
    } catch (e) { setError((e as Error).message); return []; }
  }, [kase.id]);

  useEffect(() => {
    casePlaybooks(kase.id).then(setPlaybooks).catch((e: Error) => setError(e.message));
    refreshRuns().then((list) => { if (list[0]) getRun(kase.id, list[0].id).then(setCurrent).catch(() => undefined); });
  }, [kase.id, refreshRuns]);

  // A run that is reading, or waiting on something a colleague may answer: poll it, so the thread moves for everyone.
  useEffect(() => {
    if (!current || !["reading", "waiting", "paused"].includes(current.status)) return;
    timer.current = window.setTimeout(async () => {
      try { setCurrent(await getRun(kase.id, current.id)); } catch (e) { setError((e as Error).message); }
    }, current.status === "reading" ? POLL_MS : POLL_MS * 4);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [current, kase.id]);

  const playbook = playbooks?.find((p) => p.slug === "deed-intake") ?? playbooks?.[0] ?? null;
  const live = current && ["reading", "waiting", "paused"].includes(current.status);
  const start = async () => {
    if (!playbook) return;
    setBusy(true);
    setError(null);
    try {
      const run = await startRun(kase.id, playbook.slug, lang());
      setCurrent(run);
      await refreshRuns();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const changed = async (run: Run) => {
    setCurrent(run);
    await refreshRuns();
    if (run.status === "done") onDocumentsChanged();
  };
  const words = playbookWords(playbooks?.find((p) => p.id === current?.playbook_id) ?? playbook, language);

  return (
    <section className="view playbook-view">
      <header className="view-head">
        <TextButton onPress={onBack}><ArrowLeft size={14} aria-hidden /> {m.backToChat}</TextButton>
        <h1><ClipboardList size={18} aria-hidden /> {words.title || m.playbooks}</h1>
      </header>
      <p className="view-intro">{m.playbookIntro}</p>
      {playbooks && !playbook && <p className="caption">{m.noPlaybookForType}</p>}
      {playbook && !playbook.covered && (
        <InlineNotice icon={<AlertTriangle size={14} />}>{m.playbookNotCovered}</InlineNotice>
      )}
      {playbook && canRun && kase.state === "open" && !live && (
        <div className="playbook-start">
          <Button onPress={start} isDisabled={busy}><Play size={14} aria-hidden /> {current ? m.runAgain : m.startRoutine}</Button>
          <span className="caption">{m.playbookVersion(playbook.version)}</span>
        </div>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      {current && (
        <RunView key={current.id} run={current} kase={kase} nameOf={nameOf} me={me} canRun={canRun && kase.state === "open"} documents={documents}
                 words={words} playbook={playbooks?.find((p) => p.id === current.playbook_id) ?? playbook}
                 onChanged={changed} onDocumentsChanged={onDocumentsChanged} />
      )}
      {runs.length > 1 && (
        <section className="playbook-runs" aria-labelledby="earlier-runs">
          <h2 id="earlier-runs" className="label">{m.earlierRuns}</h2>
          <ul>
            {runs.filter((r) => r.id !== current?.id).map((r) => (
              <li key={r.id}>
                <TextButton link onPress={() => getRun(kase.id, r.id).then(setCurrent).catch((e: Error) => setError(e.message))}>
                  {dayLabel(r.started_at)} · {statusLabel(r.status, m)}{r.out_of_date ? ` · ${m.runOutOfDate}` : ""}
                </TextButton>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}

export function statusLabel(status: RunStatus, m: Words): string {
  return { reading: m.runReading, waiting: m.runWaiting, paused: m.runPaused, done: m.runDone, stopped: m.runStopped,
           cancelled: m.runCancelled, failed: m.runFailed }[status] ?? status;
}

/** The step's name, for the banner and the chip: the kind in words, since the playbook names its steps for the machine. */
export function stepLabel(run: Pick<RunSummary, "step" | "status">, playbook: Pick<PlaybookInfo, "steps"> | null | undefined, m: Words): string {
  const kind = playbook?.steps?.find((s) => s.id === run.step)?.kind ?? (run.step === "confirm" ? "checkpoint" : run.step === "read" ? "read" : null);
  if (run.status === "reading" || kind === "read") return m.stepReading;
  const names: Record<string, string> = { request: m.stepRequest, ask: m.stepAsk, checkpoint: m.stepCheckpoint, produce: m.stepProduce };
  return names[kind ?? ""] ?? "";
}

/** One line for the chip on a case: the playbook's title and what the run waits for. */
export function runChipText(run: RunSummary, playbook: Pick<PlaybookInfo, "steps" | "name" | "text"> | null | undefined, title: string, m: Words): string {
  const what = run.status === "paused" ? m.runPaused : stepLabel(run, playbook, m);
  return what ? `${title} · ${what}` : title;
}

function errorLabel(error: string | null, m: Words): string {
  const known: Record<string, string> = {
    unreadable_answer: m.runErrorUnreadable, model_unavailable: m.runErrorModel, documents_unavailable: m.runErrorDocuments,
    interrupted: m.runErrorInterrupted, busy: m.runErrorBusy,
    document_missing: m.runErrorDocuments, server_error: m.runErrorServer,
  };
  return known[error ?? ""] ?? m.runErrorServer;
}

function RunView({ run, kase, canRun, me, documents, words, playbook, onChanged, onDocumentsChanged, nameOf }: {
  run: Run; kase: Case; canRun: boolean; me?: string; documents: number; words: PlaybookWords; playbook: PlaybookInfo | null;
  onChanged: (run: Run) => void; onDocumentsChanged: () => void; nameOf: (username: string) => string;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const step = playbook?.steps?.find((s) => s.id === run.step) ?? null;
  const live = ["reading", "waiting", "paused"].includes(run.status);
  const legacy = Object.keys(run.steps).length === 0;
  const mayEnd = live && !legacy && (run.starter === me || kase.manager === me);
  const act = async (action: "pause" | "resume" | "stop" | "cancel") => {
    setBusy(true);
    setError(null);
    try { onChanged(await runAction(kase.id, run.id, action, action === "cancel" ? reason : "")); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); setCancelling(false); setReason(""); }
  };
  const menu: MenuEntry[] = [
    run.status === "paused"
      ? { id: "resume", label: m.resumeRun, icon: <Play size={16} /> }
      : { id: "pause", label: m.pauseRun, icon: <Pause size={16} />, isDisabled: run.status !== "waiting" },
    "-",
    { id: "stop", label: m.stopRun, icon: <Square size={16} />, isDisabled: !mayEnd, description: m.stopRunHint },
    { id: "cancel", label: m.cancelRun, icon: <XCircle size={16} />, isDisabled: !mayEnd, description: m.cancelRunHint },
  ];
  return (
    <section className="playbook-run" aria-live="polite">
      <RunBanner run={run} playbook={playbook} words={words} nameOf={nameOf} />
      {run.status === "failed" && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{errorLabel(run.error, m)}</InlineNotice>}
      {run.out_of_date && <InlineNotice icon={<AlertTriangle size={14} />}>{m.runOutOfDateHint}</InlineNotice>}
      {run.instruction_like_sources.length > 0 && (
        <InlineNotice icon={<AlertTriangle size={14} />}>{m.runSuspiciousSources}</InlineNotice>
      )}
      {legacy && live && <InlineNotice icon={<AlertTriangle size={14} />}>{m.runFromEarlierVersion}</InlineNotice>}
      {run.status === "cancelled" && <InlineNotice icon={<XCircle size={14} />}>{m.runCancelledHint(nameOf(run.ended_by ?? ""), run.ended_reason ?? "")}</InlineNotice>}
      {run.status === "stopped" && <InlineNotice icon={<Square size={14} />}>{m.runStoppedHint(nameOf(run.ended_by ?? ""))}</InlineNotice>}
      <div className="playbook-body">
        <div className="playbook-thread-column">
          <Thread turns={run.turns} nameOf={nameOf} words={words} />
          {live && !legacy && canRun && run.status === "waiting" && step && (
            <Composer run={run} step={step} kase={kase} words={words} documents={documents} onChanged={onChanged}
                      onDocumentsChanged={onDocumentsChanged} />
          )}
          {live && run.status === "waiting" && !canRun && (
            <p className="caption">{kase.state === "closed" ? m.checkpointCaseClosed : m.checkpointReadOnly}</p>
          )}
          {run.status === "paused" && <p className="caption">{m.pausedHint}</p>}
        </div>
        <aside className="playbook-panel" aria-label={m.factsPanel}>
          <FactsPanel run={run} words={words} kase={kase} nameOf={nameOf} />
        </aside>
      </div>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      {live && !legacy && canRun && (
        <div className="playbook-run-menu">
          <ActionMenu aria-label={m.runMenu} menuLabel={m.runMenu} entries={menu} isDisabled={busy}
                      onAction={(id) => { if (id === "cancel") setCancelling(true); else void act(id as "pause" | "resume" | "stop"); }}>
            <MoreHorizontal size={16} aria-hidden /> {m.runMenu}
          </ActionMenu>
        </div>
      )}
      <Dialog isOpen={cancelling} onClose={() => setCancelling(false)} title={m.cancelRun} busy={busy}
              actions={<>
                <Button variant="secondary" onPress={() => setCancelling(false)}>{m.keepRunning}</Button>
                <Button variant="primary" onPress={() => void act("cancel")} isDisabled={busy}>{m.cancelRunConfirm}</Button>
              </>}>
        <p>{m.cancelRunExplain}</p>
        <TextArea label={m.cancelReason} value={reason} onChange={setReason} rows={2} />
      </Dialog>
    </section>
  );
}

/** The banner: the title and version, where the run is, what it waits for and from whom, since when. */
export function RunBanner({ run, playbook, words, nameOf }: {
  run: RunSummary & { steps?: Record<string, { at: string | null }> }; playbook: PlaybookInfo | null | undefined; words: PlaybookWords;
  nameOf: (u: string) => string;
}) {
  const m = useT();
  const what = stepLabel(run, playbook, m);
  const since = (run.step && run.steps?.[run.step]?.at) || run.started_at;
  return (
    <div className="playbook-banner" data-status={run.status}>
      <div className="playbook-banner-main">
        <span className="label" data-status={run.status}>{statusLabel(run.status, m)}</span>
        <span className="playbook-banner-title"><b>{words.title}</b> {run.playbook_version}</span>
        {what && <span className="playbook-banner-step">{what}</span>}
      </div>
      <span className="caption">
        {run.status === "paused" && run.paused_by
          ? m.pausedBy(nameOf(run.paused_by), dayLabel(run.paused_at ?? run.started_at))
          : run.status === "waiting" ? m.waitingSince(dayLabel(since))
          : m.runStartedBy(nameOf(run.started_by), dayLabel(run.started_at))}
        {run.status === "reading" && run.model ? ` · ${run.model}` : ""}
        {run.status === "reading" && <> <Loader2 size={12} aria-hidden className="spin" /></>}
      </span>
    </div>
  );
}

function Thread({ turns, nameOf, words }: { turns: RunTurn[]; nameOf: (u: string) => string; words: PlaybookWords }) {
  const m = useT();
  if (turns.length === 0) return <p className="caption">{m.threadEmpty}</p>;
  return (
    <ol className="playbook-thread" aria-label={m.thread}>
      {turns.map((t) => (
        <li key={t.seq} className={t.role === "playbook" || t.role === "assistant" ? "turn-assistant" : "turn-user"}>
          {t.role === "playbook" || t.role === "assistant" ? (
            <>
              <AssistantMark />
              <div className="playbook-turn">
                <p>{t.text}</p>
                {typeof t.meta.fact === "string" && <span className="ui-eyebrow">{words.labels[t.meta.fact] ?? t.meta.fact}</span>}
              </div>
            </>
          ) : (
            <>
              <div className="bubble">{t.text}</div>
              <span className="caption">{nameOf(t.by)} · {dayLabel(t.at)}</span>
            </>
          )}
        </li>
      ))}
    </ol>
  );
}

/** What the person answers with, for the step the run waits on. */
function Composer({ run, step, kase, words, documents, onChanged, onDocumentsChanged }: {
  run: Run; step: NonNullable<PlaybookInfo["steps"]>[number]; kase: Case; words: PlaybookWords; documents: number;
  onChanged: (run: Run) => void; onDocumentsChanged: () => void;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const asked = useMemo(() => run.turns.filter((t) => t.step_id === step.id && t.role === "playbook" && typeof t.meta.fact === "string")
                                        .map((t) => t.meta.fact as string), [run.turns, step.id]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(run.facts.map((f) => [f.id, f.confirmed ?? f.value])));
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { setValues(Object.fromEntries(run.facts.map((f) => [f.id, f.confirmed ?? f.value]))); }, [run]);

  const send = async (fn: () => Promise<Run>) => {
    setBusy(true);
    setError(null);
    try { onChanged(await fn()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const upload = async (files: File[]) => {
    setError(null);
    for (const f of files) {
      setUploading(f.name);
      try { await uploadDocument(f, undefined, kase.id); } catch (e) { setError((e as Error).message); }
    }
    setUploading(null);
    onDocumentsChanged();
  };

  if (step.kind === "request") {
    return (
      <div className="playbook-composer">
        <div className="playbook-actions">
          <FileButton accept={UPLOAD_TYPES} multiple onSelect={(files) => void upload(files)}>
            <Button variant="secondary" isDisabled={busy || uploading !== null}>
              {uploading ? <Loader2 size={14} aria-hidden className="spin" /> : <Paperclip size={14} aria-hidden />} {uploading ? m.uploadingFile(uploading) : m.addDocuments}
            </Button>
          </FileButton>
          <Button onPress={() => void send(() => answerRun(kase.id, run.id, step.id, { text: m.documentsAreIn }))} isDisabled={busy || documents === 0}>
            <ArrowUp size={14} aria-hidden /> {m.continueRun}
          </Button>
          <span className="caption">{documents === 0 ? m.noDocumentsYet : m.documentsInCase(documents)}</span>
        </div>
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      </div>
    );
  }
  if (step.kind === "ask") {
    return (
      <div className="playbook-composer">
        <p className="caption">{m.askIntro(asked.length)}</p>
        <ol className="playbook-facts">
          {asked.map((id) => (
            <li key={id} className="playbook-fact" data-found="false">
              <div className="playbook-fact-main">
                <span className="ui-eyebrow">{words.labels[id] ?? id}</span>
                <TextArea label={stepQuestion(words, step.id, id)} hideLabel value={answers[id] ?? ""} rows={1} className="playbook-fact-field"
                          placeholder={m.answerPlaceholder} onChange={(v) => setAnswers((a) => ({ ...a, [id]: v }))} />
              </div>
            </li>
          ))}
        </ol>
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
        <div className="playbook-actions">
          <Button onPress={() => void send(() => answerRun(kase.id, run.id, step.id, { facts: answers }))} isDisabled={busy}>
            <ArrowUp size={14} aria-hidden /> {Object.values(answers).some((v) => v.trim()) ? m.sendAnswers : m.dontKnowYet}
          </Button>
        </div>
      </div>
    );
  }
  if (step.kind === "checkpoint") {
    const checked = run.facts.filter((f) => f.found || f.source === "person").length;
    return (
      <div className="playbook-composer">
        <p className="caption">{m.checkpointIntro(checked, run.facts.length)}</p>
        <ol className="playbook-facts">
          {run.facts.map((f) => (
            <FactRow key={f.id} fact={f} label={words.labels[f.id] ?? f.id} value={values[f.id] ?? ""} editable
                     open={open === f.id} onOpen={() => setOpen(open === f.id ? null : f.id)}
                     onChange={(v) => setValues((vs) => ({ ...vs, [f.id]: v }))} />
          ))}
        </ol>
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
        <div className="playbook-actions">
          <Button onPress={() => void send(() => confirmRun(kase.id, run.id, run.facts.map((f) => ({ id: f.id, confirmed: values[f.id] ?? "" })), lang()))}
                  isDisabled={busy}>{busy ? m.saving : m.confirmAll}</Button>
        </div>
      </div>
    );
  }
  return null;
}

/** The facts beside the thread: each with its status; the product when the run is done. */
function FactsPanel({ run, words, kase, nameOf }: { run: Run; words: PlaybookWords; kase: Case; nameOf: (u: string) => string }) {
  const m = useT();
  const [open, setOpen] = useState<string | null>(null);
  const mark = useWatermark();
  const word = async () => {
    const blob = await intakeToWord({
      title: `${words.title} ${kase.reference}`, caseName: kase.name, version: m.playbookVersion(run.playbook_version),
      confirmedOn: m.confirmedBy(run.confirmed_by ? nameOf(run.confirmed_by) : "", new Date(run.confirmed_at ?? run.started_at).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" })),
      facts: run.facts.map((f) => ({ label: words.labels[f.id] ?? f.id, value: f.confirmed ?? f.value,
                                    sources: f.citations.map((c) => `${c.filename}${c.page ? ` p. ${c.page}` : ""}`) })),
      sourcesHeading: m.sourcesHeading, emptyValue: m.factNotFound, disclaimer: m.wordDisclaimer,
      // sūveryn's mark (lib/marks.ts): uploaded again, this file asks before it becomes a source
      mark: m.exportMark("playbook", kase.reference, new Date().toLocaleDateString(locale()), exportRef("P", run.id))
        + (mark() ? ` · ${m.strictlyConfidential}` : ""),
      watermark: mark(),  // a strictly confidential case (§11)
    });
    saveBlob(`${words.title} ${kase.reference}.docx`.replace(/[/\\]/g, "-"), blob);
  };
  if (run.facts.length === 0) {
    return <p className="caption">{run.status === "reading" ? m.runReadingHint(run.documents.length) : m.noFactsYet}</p>;
  }
  const status = (f: RunFact) => f.confirmed !== null ? (f.confirmed ? m.factConfirmed : m.factCleared)
    : f.source === "person" ? m.factAnswered : f.found ? m.factRead : m.factNotFound;
  return (
    <>
      <h2 className="label">{m.factsPanel}</h2>
      <ol className="playbook-facts playbook-facts-compact">
        {run.facts.map((f) => (
          <FactRow key={f.id} fact={f} label={words.labels[f.id] ?? f.id} value={f.confirmed ?? f.value} editable={false}
                   status={status(f)} open={open === f.id} onOpen={() => setOpen(open === f.id ? null : f.id)} onChange={() => undefined} />
        ))}
      </ol>
      {run.status === "done" && (
        <div className="playbook-actions">
          <Button onPress={word} variant="secondary"><Download size={14} aria-hidden /> {m.downloadWord}</Button>
          {run.result_document_id && <span className="caption"><FileText size={12} aria-hidden /> {m.summaryInCase}</span>}
        </div>
      )}
    </>
  );
}

function FactRow({ fact, label, value, editable, status, open, onOpen, onChange }: {
  fact: RunFact; label: string; value: string; editable: boolean; status?: string; open: boolean; onOpen: () => void; onChange: (v: string) => void;
}) {
  const m = useT();
  const first = fact.citations[0];
  const citation: Citation | null = first ? { text: first.text, source: { document_id: first.document_id, page: first.page, location: first.location } } : null;
  const corrected = fact.confirmed !== null && fact.confirmed !== fact.value;
  return (
    <li className="playbook-fact" data-found={fact.found} data-issues={fact.issues.length > 0 || undefined} data-confirmed={fact.confirmed !== null || undefined}>
      <div className="playbook-fact-main">
        <span className="ui-eyebrow">{label}</span>
        {editable ? (
          <TextArea label={label} hideLabel value={value} onChange={onChange} rows={1} className="playbook-fact-field"
                    placeholder={fact.found || fact.source === "person" ? "" : m.factNotFound} />
        ) : (
          <span className="playbook-fact-value">{value || <em>{m.factNotFound}</em>}</span>
        )}
        <span className="playbook-fact-meta">
          {status && <span className="playbook-fact-status">{fact.confirmed !== null && <Check size={12} aria-hidden />} {status}</span>}
          {first ? (
            <TextButton className="playbook-fact-source" onPress={onOpen} aria-expanded={open}>
              <FileText size={12} aria-hidden /> {first.filename}{first.page ? `, p. ${first.page}` : ""}
              {fact.citations.length > 1 ? ` +${fact.citations.length - 1}` : ""}
            </TextButton>
          ) : (
            <span className="caption">{fact.source === "person" ? m.factFromPerson : fact.found ? m.factNoSource : m.factNotInDocuments}</span>
          )}
          {fact.issues.length > 0 && (
            <span className="playbook-fact-issue"><AlertTriangle size={12} aria-hidden /> {m.factToCheck(fact.issues.join(", "))}</span>
          )}
          {corrected && <span className="caption">{m.factCorrected(fact.value || m.factNotFound)}</span>}
        </span>
      </div>
      {open && citation && (
        <div className="playbook-fact-passage">
          <SourceCard n={first.n} citation={citation} filename={first.filename} claims={[fact.value]} />
        </div>
      )}
    </li>
  );
}
