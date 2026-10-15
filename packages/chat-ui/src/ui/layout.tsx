/**
 * Plain building blocks with no behaviour of their own (suveryn-tracker#44): the card, the step
 * indicator, a note, a list of read-only facts and chips. Shared look with the Keycloak login: see
 * the base rules at the top of ui.css.
 */
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
