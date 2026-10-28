/**
 * Playbooks in a case (suveryn-tracker#51, docs/design/playbooks.md): the first one, deed intake.
 * The view takes the conversation's place, like Usage: start a run on the case's uploaded documents,
 * follow it, then the checkpoint: every fact next to the passage it was read from, with the check's
 * warning when there is one, and a field to confirm or correct it. After confirmation: the summary,
 * a Word download (made in the browser, as answers are), and the document in the case's list.
 * Earlier runs are listed under the current one. A reader sees runs; only a contributor starts or
 * confirms (the gateway decides; the view only hides what would fail).
 */
import { AlertCircle, AlertTriangle, ArrowLeft, ClipboardList, Download, FileText, Loader2, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  casePlaybooks, confirmRun, getRun, listRuns, startRun,
  type Case, type Citation, type PlaybookInfo, type Run, type RunFact, type RunSummary,
} from "../api";
import { useWatermark } from "../lib/watermark";
import { lang, locale, useLang, useT } from "../i18n";
import { playbookWords, type PlaybookWords } from "../lib/playbooks";
import { dayLabel } from "../lib/conversations";
import { exportRef } from "../lib/marks";
import { intakeToWord, saveBlob } from "../lib/office";
import { Button, InlineNotice, TextArea, TextButton } from "../ui";
import { SourceCard } from "./Messages";

const POLL_MS = 1500;


export function PlaybookView({ kase, canRun, documents, onBack, onDocumentsChanged }: {
  kase: Case; canRun: boolean; documents: number; onBack: () => void; onDocumentsChanged: () => void;
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

  // A run that is still reading: poll it until it reaches the checkpoint or fails.
  useEffect(() => {
    if (current?.status !== "reading") return;
    timer.current = window.setTimeout(async () => {
      try { setCurrent(await getRun(kase.id, current.id)); } catch (e) { setError((e as Error).message); }
    }, POLL_MS);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [current, kase.id]);

  const deedIntake = playbooks?.find((p) => p.slug === "deed-intake") ?? null;
  const start = async () => {
    if (!deedIntake) return;
    setBusy(true);
    setError(null);
    try {
      const run = await startRun(kase.id, deedIntake.slug);
      setCurrent(run);
      await refreshRuns();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const confirmed = async (run: Run) => {
    setCurrent(run);
    await refreshRuns();
    onDocumentsChanged();
  };

  return (
    <section className="view playbook-view">
      <header className="view-head">
        <TextButton onPress={onBack}><ArrowLeft size={14} aria-hidden /> {m.backToChat}</TextButton>
        <h1><ClipboardList size={18} aria-hidden /> {playbookWords(deedIntake, language).title || m.playbooks}</h1>
      </header>
      <p className="view-intro">{m.playbookIntro}</p>
      {playbooks && !deedIntake && <p className="caption">{m.noPlaybookForType}</p>}
      {deedIntake && !deedIntake.covered && (
        <InlineNotice icon={<AlertTriangle size={14} />}>{m.playbookNotCovered}</InlineNotice>
      )}
      {deedIntake && canRun && kase.state === "open" && current?.status !== "reading" && (
        <div className="playbook-start">
          <Button onPress={start} isDisabled={busy || documents === 0}><Play size={14} aria-hidden /> {current ? m.runAgain : m.startIntake}</Button>
          <span className="caption">{documents === 0 ? m.noDocumentsToRead : m.playbookVersion(deedIntake.version)}</span>
        </div>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      {current && <RunPanel key={current.id} run={current} kase={kase} canRun={canRun && kase.state === "open"} onConfirmed={confirmed}
                            words={playbookWords(playbooks?.find((p) => p.id === current.playbook_id) ?? deedIntake, language)} />}
      {runs.length > 1 && (
        <section className="playbook-runs" aria-labelledby="earlier-runs">
          <h2 id="earlier-runs" className="label">{m.earlierRuns}</h2>
          <ul>
            {runs.filter((r) => r.id !== current?.id).map((r) => (
              <li key={r.id}>
                <TextButton onPress={() => getRun(kase.id, r.id).then(setCurrent).catch((e: Error) => setError(e.message))}>
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

function statusLabel(status: Run["status"], m: ReturnType<typeof useT>): string {
  return { reading: m.runReading, checkpoint: m.runCheckpoint, confirmed: m.runConfirmed, failed: m.runFailed }[status];
}

function errorLabel(error: string | null, m: ReturnType<typeof useT>): string {
  const known: Record<string, string> = {
    unreadable_answer: m.runErrorUnreadable, model_unavailable: m.runErrorModel, documents_unavailable: m.runErrorDocuments,
    interrupted: m.runErrorInterrupted,
    document_missing: m.runErrorDocuments, server_error: m.runErrorServer,
  };
  return known[error ?? ""] ?? m.runErrorServer;
}

function RunPanel({ run, kase, canRun, words, onConfirmed }: {
  run: Run; kase: Case; canRun: boolean; onConfirmed: (run: Run) => void;
  /** The run's playbook's words in the interface language (its title and fact labels). */
  words: PlaybookWords;
}) {
  const m = useT();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(run.facts.map((f) => [f.id, f.confirmed ?? f.value])));
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setValues(Object.fromEntries(run.facts.map((f) => [f.id, f.confirmed ?? f.value]))); }, [run]);
  const atCheckpoint = run.status === "checkpoint";
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      onConfirmed(await confirmRun(kase.id, run.id, run.facts.map((f) => ({ id: f.id, confirmed: values[f.id] ?? "" })), lang()));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const mark = useWatermark();
  const word = async () => {
    const blob = await intakeToWord({
      title: `${words.title} ${kase.reference}`, caseName: kase.name, version: m.playbookVersion(run.playbook_version),
      confirmedOn: m.confirmedBy(run.confirmed_by ?? "", new Date(run.confirmed_at ?? run.started_at).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" })),
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
  const checked = useMemo(() => run.facts.filter((f) => f.found).length, [run]);
  return (
    <section className="playbook-run" aria-live="polite">
      <div className="playbook-run-head">
        <span className="label">{statusLabel(run.status, m)}</span>
        <span className="caption">
          {m.runStartedBy(run.started_by, dayLabel(run.started_at))}
          {run.model ? ` · ${run.model}` : ""}
        </span>
      </div>
      {run.status === "reading" && (
        <p className="playbook-reading"><Loader2 size={14} aria-hidden className="spin" /> {m.runReadingHint(run.documents.length)}</p>
      )}
      {run.status === "failed" && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{errorLabel(run.error, m)}</InlineNotice>}
      {run.out_of_date && <InlineNotice icon={<AlertTriangle size={14} />}>{m.runOutOfDateHint}</InlineNotice>}
      {run.instruction_like_sources.length > 0 && (
        <InlineNotice icon={<AlertTriangle size={14} />}>{m.runSuspiciousSources}</InlineNotice>
      )}
      {(atCheckpoint || run.status === "confirmed") && (
        <>
          <p className="caption">{atCheckpoint ? m.checkpointIntro(checked, run.facts.length) : m.confirmedIntro}</p>
          <ol className="playbook-facts">
            {run.facts.map((f) => (
              <FactRow key={f.id} fact={f} label={words.labels[f.id] ?? f.id} value={values[f.id] ?? ""} editable={atCheckpoint && canRun}
                       open={open === f.id} onOpen={() => setOpen(open === f.id ? null : f.id)}
                       onChange={(v) => setValues((vs) => ({ ...vs, [f.id]: v }))} />
            ))}
          </ol>
          {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
          <div className="playbook-actions">
            {atCheckpoint && canRun && (
              <Button onPress={confirm} isDisabled={busy}>{busy ? m.saving : m.confirmAll}</Button>
            )}
            {atCheckpoint && !canRun && <span className="caption">{kase.state === "closed" ? m.checkpointCaseClosed : m.checkpointReadOnly}</span>}
            {run.status === "confirmed" && (
              <>
                <Button onPress={word} variant="secondary"><Download size={14} aria-hidden /> {m.downloadWord}</Button>
                {run.result_document_id && <span className="caption"><FileText size={12} aria-hidden /> {m.summaryInCase}</span>}
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function FactRow({ fact, label, value, editable, open, onOpen, onChange }: {
  fact: RunFact; label: string; value: string; editable: boolean; open: boolean; onOpen: () => void; onChange: (v: string) => void;
}) {
  const m = useT();
  const first = fact.citations[0];
  const citation: Citation | null = first ? { text: first.text, source: { document_id: first.document_id, page: first.page, location: first.location } } : null;
  const corrected = fact.confirmed !== null && fact.confirmed !== fact.value;
  return (
    <li className="playbook-fact" data-found={fact.found} data-issues={fact.issues.length > 0 || undefined}>
      <div className="playbook-fact-main">
        <span className="ui-eyebrow">{label}</span>
        {editable ? (
          <TextArea label={label} hideLabel value={value} onChange={onChange} rows={1} className="playbook-fact-field"
                    placeholder={fact.found ? "" : m.factNotFound} />
        ) : (
          <span className="playbook-fact-value">{value || <em>{m.factNotFound}</em>}</span>
        )}
        <span className="playbook-fact-meta">
          {first ? (
            <TextButton className="playbook-fact-source" onPress={onOpen} aria-expanded={open}>
              <FileText size={12} aria-hidden /> {first.filename}{first.page ? `, p. ${first.page}` : ""}
              {fact.citations.length > 1 ? ` +${fact.citations.length - 1}` : ""}
            </TextButton>
          ) : (
            <span className="caption">{fact.found ? m.factNoSource : m.factNotInDocuments}</span>
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
