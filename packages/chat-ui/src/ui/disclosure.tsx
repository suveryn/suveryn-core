/**
 * A row that expands in place (docs/design/chat-ui.md): the sidebar's "Conversations", "Cases" and
 * "Documents", and a pinned case with its conversations. Two controls in one row: the label is a
 * button of its own (it opens the full view), the chevron toggles the panel under it. The panel is
 * a plain region; what is in it is the caller's. With no `onOpen`, the whole row toggles.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Button as AriaButton } from "react-aria-components";
import { cx } from "./Button";

export function Expander({ label, icon, meta, expanded, onToggle, onOpen, title, current, actions, toggleLabel, toggleFirst, className, children }: {
  label: ReactNode;
  icon?: ReactNode;
  /** A short text after the label (a count). */
  meta?: ReactNode;
  expanded: boolean;
  onToggle: (expanded: boolean) => void;
  /** Pressing the label: opens something (a view, a case). Without it, the label toggles the panel too. */
  onOpen?: () => void;
  /** The row's tooltip. */
  title?: string;
  /** The row names what is open now. */
  current?: boolean;
  /** Controls after the chevron (a case's actions menu). */
  actions?: ReactNode;
  /** The chevron's accessible name ("Show conversations"). */
  toggleLabel: string;
  /** The chevron before the icon, pointing right when closed and down when open (a pinned case,
   *  docs/design/chat-ui.md §2); otherwise after the label. */
  toggleFirst?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const panel = useId();
  const toggle = onOpen && (
    <AriaButton className="ui-expander-toggle" onPress={() => onToggle(!expanded)} aria-expanded={expanded}
                aria-controls={panel} aria-label={toggleLabel}>
      {toggleFirst ? <ChevronRight size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
    </AriaButton>
  );
  return (
    <div className={cx("ui-expander", className)} data-expanded={expanded || undefined} data-toggle-first={toggleFirst || undefined}>
      <div className="ui-expander-row" title={title}>
        {toggleFirst && toggle}
        <AriaButton className="ui-expander-label" onPress={onOpen ?? (() => onToggle(!expanded))}
                    aria-current={current ? "page" : undefined} aria-expanded={onOpen ? undefined : expanded}
                    aria-controls={onOpen ? undefined : panel}>
          {icon && <span className="ui-expander-icon" aria-hidden>{icon}</span>}
          <span className="ui-expander-text">{label}</span>
          {meta !== undefined && <span className="ui-expander-meta">{meta}</span>}
        </AriaButton>
        {!toggleFirst && toggle}
        {actions}
      </div>
      <div id={panel} className="ui-expander-panel" hidden={!expanded}>{expanded && children}</div>
    </div>
  );
}
