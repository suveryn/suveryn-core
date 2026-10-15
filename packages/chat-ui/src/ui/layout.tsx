/**
 * Plain building blocks with no behaviour of their own (suveryn-tracker#44): the card, the step
 * indicator, a note, a list of read-only facts and chips. Shared look with the Keycloak login: see
 * the base rules at the top of ui.css.
 */
import { Check, Circle, CircleAlert, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "./Button";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("ui-card", className)}>{children}</section>;
}

/** "Setup · Step 1 of 6" and a rail of segments, the done ones filled. The text is what screen
 *  readers get; the rail is decoration. */
export function Steps({ text, step, total }: { text: string; step: number; total: number }) {
  return (
    <div className="ui-steps">
      <p className="ui-eyebrow">{text}</p>
      <div className="ui-rail" aria-hidden>
        {Array.from({ length: total }, (_, i) => <span key={i} className="ui-rail-segment" data-done={i < step || undefined} />)}
      </div>
    </div>
  );
}

export function Note({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="ui-note">
      {icon && <span className="ui-note-icon" aria-hidden>{icon}</span>}
      <span>{children}</span>
    </div>
  );
}

export type Fact = { icon?: ReactNode; label: string; value: string; detail?: string };

/** Facts the screen shows but doesn't let you change, with a footer saying where they are changed. */
export function Facts({ facts, footer }: { facts: Fact[]; footer?: ReactNode }) {
  return (
    <div className="ui-facts">
      <ul>
        {facts.map((f) => (
          <li key={f.label} className="ui-fact">
            {f.icon && <span className="ui-fact-icon" aria-hidden>{f.icon}</span>}
            <div>
              <span className="ui-eyebrow">{f.label}</span>
              <span className="ui-fact-value">{f.value}</span>
              {f.detail && <span className="ui-fact-detail">{f.detail}</span>}
            </div>
          </li>
        ))}
      </ul>
      {footer && <div className="ui-facts-footer">{footer}</div>}
    </div>
  );
}

export function Chips({ items, label }: { items: string[]; label?: string }) {
  return (
    <ul className="ui-chips" aria-label={label}>
      {items.map((i) => <li key={i} className="ui-chip">{i}</li>)}
    </ul>
  );
}

/** Rows of label and value (the review, the support agreement): a description list. A row may end
 *  with an action, such as an Edit link back to its step. */
export type Row = { label: string; value: ReactNode; detail?: ReactNode; action?: ReactNode; tone?: "ok" };
export function Rows({ rows }: { rows: Row[] }) {
  return (
    <dl className="ui-rows">
      {rows.map((r) => (
        <div key={r.label} className="ui-row">
          <dt className="ui-eyebrow ui-row-label">{r.label}</dt>
          <dd className="ui-row-value">
            <span className="ui-row-main" data-tone={r.tone}>{r.value}</span>
            {r.detail && <span className="ui-row-detail">{r.detail}</span>}
          </dd>
          {r.action && <dd className="ui-row-action">{r.action}</dd>}
        </div>
      ))}
    </dl>
  );
}

/** A list of steps with their state (provisioning, the finished setup). The state is in the icon
 *  and, for screen readers, in words. */
export type Status = "done" | "running" | "waiting" | "failed";
export type StatusItem = { id: string; label: string; detail?: string; state: Status; stateText: string };
export function StatusList({ items }: { items: StatusItem[] }) {
  return (
    <ul className="ui-status-list">
      {items.map((i) => (
        <li key={i.id} className="ui-status" data-state={i.state}>
          <span className="ui-status-icon" aria-hidden>{STATUS_ICON[i.state]}</span>
          <span className="ui-status-label">{i.label}<span className="ui-visually-hidden">, {i.stateText}</span></span>
          {i.detail && <span className="ui-status-detail">{i.detail}</span>}
        </li>
      ))}
    </ul>
  );
}
const STATUS_ICON: Record<Status, ReactNode> = {
  done: <Check size={16} />,
  running: <LoaderCircle size={16} className="ui-spin" />,
  waiting: <Circle size={16} />,
  failed: <CircleAlert size={16} />,
};

/** A boxed message: a note (neutral) or a warning (accent-ink border and icon: the brand has no red). */
export function Notice({ icon, title, children, tone = "note" }: { icon: ReactNode; title?: string; children?: ReactNode;
                                                                   tone?: "note" | "warning" }) {
  return (
    <div className="ui-notice" data-tone={tone}>
      <span className="ui-note-icon" aria-hidden>{icon}</span>
      <span>
        {title && <b className="ui-notice-title">{title}</b>}
        {children && <span className="ui-notice-text">{children}</span>}
      </span>
    </div>
  );
}
