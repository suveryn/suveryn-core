/**
 * A source, the same everywhere (handover of 31 October 2026, "one rule for sources"): the teal marker
 * and the file and page, one link. Under an answer (the sources line), under a fact in a playbook's
 * card and in the facts list. Pressing it opens the source panel on that source; the open one's marker
 * is filled teal with ink text and the link says so (`aria-current`). `name` is its accessible name
 * ("Source 1: deed.pdf, page 4"), `text` what it shows after the marker ("deed.pdf, p. 4").
 */
import { Button as AriaButton } from "react-aria-components";
import { cx } from "./Button";

export function SourceRef({ n, text, name, active = false, removed = false, onPress, className }: {
  n: number; text: string; name: string; active?: boolean; removed?: boolean; onPress: () => void; className?: string;
}) {
  return (
    <AriaButton className={cx("ui-source-ref", className)} onPress={onPress} aria-label={name}
                aria-current={active ? "true" : undefined} data-active={active || undefined} data-removed={removed || undefined}>
      <span className="ui-source-ref-n" aria-hidden>{n}</span>
      <span className="ui-source-ref-text">{text}</span>
    </AriaButton>
  );
}
