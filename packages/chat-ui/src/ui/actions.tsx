/**
 * Small actions and indicators (suveryn-tracker#37, #44): a link that looks like a button, a copy
 * button that says when it copied, a progress bar, and a toolbar (one Tab stop; the arrow keys move
 * between its buttons).
 */
import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link as AriaLink, ProgressBar, Toolbar as AriaToolbar } from "react-aria-components";
import { Button, cx } from "./Button";

/** A link (it goes somewhere) styled as a button, or as a quiet text link with variant "text". */
export function LinkButton({ href, children, variant = "primary", className, newTab }: {
  href: string; children: ReactNode; variant?: "primary" | "secondary" | "text"; className?: string;
  /** Opens in a new tab (another site: the account console). */
  newTab?: boolean;
}) {
  return (
    <AriaLink href={href} className={cx(variant === "text" ? "ui-text-link" : "ui-button", className)}
              data-variant={variant === "text" ? undefined : variant} target={newTab ? "_blank" : undefined} rel={newTab ? "noopener" : undefined}>
      {children}
    </AriaLink>
  );
}

/**
 * Copies `text`. The label changes to `copiedLabel` for a few seconds, which a screen reader announces
 * (a live region). If the browser refuses the clipboard, `onFail` can point the person to the text.
 */
export function CopyButton({ text, label, copiedLabel, onFail }: { text: string; label: string; copiedLabel: string;
                                                                  onFail?: () => void }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 3000);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <>
      <Button size="small" onPress={async () => {
        try { await navigator.clipboard.writeText(text); setCopied(true); } catch { onFail?.(); }
      }}>
        {copied ? <Check size={14} aria-hidden className="ui-icon-ok" /> : <Copy size={14} aria-hidden />}
        {copied ? copiedLabel : label}
      </Button>
      <span className="ui-visually-hidden" role="status">{copied ? copiedLabel : ""}</span>
    </>
  );
}

/** A progress bar with a visible label (what is happening now). Without ``value`` it is indeterminate:
 *  something is happening, how far along isn't known (a document being read). */
export function Progress({ value, label, valueText }: { value?: number; label: string; valueText?: string }) {
  return (
    <ProgressBar value={value} isIndeterminate={value === undefined} minValue={0} maxValue={100} className="ui-progress"
                 aria-label={label} valueLabel={valueText}>
      {({ percentage }) => (
        <span className="ui-progress-track">
          {/* A style property set through the DOM, which the CSP allows (docs/content-security-policy.md). */}
          <span className="ui-progress-fill" style={{ width: `${percentage ?? 0}%` }} />
        </span>
      )}
    </ProgressBar>
  );
}

/** A row of related buttons (an answer's actions): one Tab stop, the arrow keys move between them. */
export function Toolbar({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return <AriaToolbar aria-label={label} className={cx("ui-toolbar", className)}>{children}</AriaToolbar>;
}
