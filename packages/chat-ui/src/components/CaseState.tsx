/**
 * Cases, stage 3 (suveryn-tracker#10): the state line of a closed case, under its header.
 *
 * Says when the case was closed and what happens to it: deleted on a date (the office's keep
 * period), due for deletion soon (within a month: the warning the design asks for), marked kept,
 * or kept until someone deletes it. Its manager can reopen it; the manager and the administrators
 * can extend the period by one more, mark the case kept (never deleted by the period) or let the
 * period run again.
 */
import { CalendarPlus, CircleAlert, LockOpen, Star, StarOff, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { keepCase, reopenCase, type Case } from "../api";
import { locale, useT } from "../i18n";
import { InlineNotice, TextButton } from "../ui";

export const DUE_WARNING_DAYS = 30;  // the warning before a closed case's deletion (docs/design/cases.md, stage 3)

export const isDue = (c: Case, now: Date = new Date()): boolean =>
  c.state === "closed" && !c.keep && c.keep_until !== null &&
  new Date(c.keep_until).getTime() <= now.getTime() + DUE_WARNING_DAYS * 86_400_000;

/** A date as "3 Apr 2027", in the interface language. */
export const onDay = (iso: string): string =>
  new Date(iso).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });

/** What becomes of a closed case, in words: for the state line and the sidebar's due list. */
export function fateLabel(c: Case, m: ReturnType<typeof useT>): string {
  if (c.keep) return m.keptMarked;
  if (c.keep_until === null) return m.keptUntilDeleted;
  return isDue(c) ? m.deletedOnDue(onDay(c.keep_until)) : m.deletedOn(onDay(c.keep_until));
}

export function CaseState({ kase, canReopen, canKeep, onChanged }: {
  kase: Case; canReopen: boolean; canKeep: boolean; onChanged: (c: Case) => void;
}) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (what: () => Promise<Case>) => {
    setBusy(true);
    setError(null);
    try { onChanged(await what()); } catch (e) { setError(m.caseChangeFailed((e as Error).message)); } finally { setBusy(false); }
  };
  const due = isDue(kase);
  return (
    <div className="case-state" data-due={due || undefined}>
      {due ? <TriangleAlert size={14} aria-hidden /> : null}
      <span className="case-state-text">
        {kase.closed_at && m.closedOn(onDay(kase.closed_at))} · {fateLabel(kase, m)}
      </span>
      {canReopen && (
        <TextButton link className="case-action" onPress={() => act(() => reopenCase(kase.id))} isDisabled={busy}>
          <LockOpen size={14} aria-hidden /> {m.reopenCase}
        </TextButton>
      )}
      {canKeep && kase.keep_until !== null && !kase.keep && (
        <TextButton link className="case-action" onPress={() => act(() => keepCase(kase.id, { extend: true }))} isDisabled={busy}>
          <CalendarPlus size={14} aria-hidden /> {m.extendCase}
        </TextButton>
      )}
      {canKeep && kase.keep_until !== null && (kase.keep ? (
        <TextButton link className="case-action" onPress={() => act(() => keepCase(kase.id, { keep: false }))} isDisabled={busy}>
          <StarOff size={14} aria-hidden /> {m.unkeepCase}
        </TextButton>
      ) : (
        <TextButton link className="case-action" onPress={() => act(() => keepCase(kase.id, { keep: true }))} isDisabled={busy}>
          <Star size={14} aria-hidden /> {m.keepCase}
        </TextButton>
      ))}
      {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert className="case-state-error">{error}</InlineNotice>}
    </div>
  );
}
