/**
 * A modal dialog (docs/design/chat-ui.md, "Dialogs"; Claude Design's handover of 6 November 2026):
 * React Aria's Modal and Dialog. A screen names the dialog's kind, its title, its content and its
 * buttons by role; the kit lays the buttons out and decides where the focus starts, so no screen can
 * read the pattern differently.
 *
 * - Kinds: a *confirmation* (one action and a way out), a *choice* (two real actions and a way out),
 *   a *form* (fields, a submit and a way out), *information* (nothing to decide).
 * - One row, right-aligned, every button 44 px, in reading order: helpers (quiet, with their icon) at
 *   the left, then the way out, the second action, the main action (orange). Under 520 px, or when
 *   the labels don't fit on one row, a full-width column in the same order, the main action last.
 * - Focus starts on the main action of a confirmation or a choice; on *Cancel* when `risky`; in a
 *   form's field marked autoFocus; on an information dialog's main action, or its × when it has none. It stays inside while open and returns to what opened it.
 * - Busy: every button disabled, the running one shows its progress word, Escape and a click outside
 *   do nothing. A failure (`error`) shows under the content, the buttons come back, and the focus
 *   goes to the main action.
 * - The × (`closeLabel`) is for forms and information dialogs; confirmations and choices have their
 *   way out in the row.
 * The page behind can't scroll meanwhile: on iPhone and iPad through the attribute in ui.css
 * (docs/content-security-policy.md, exception 2).
 */
import { CircleAlert, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { Dialog as AriaDialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { Button, IconButton } from "./Button";
import { InlineNotice } from "./layout";

type DialogKind = "confirmation" | "choice" | "form" | "information";

/** A button of the row. `form` submits that form (a form dialog's main action) instead of `onPress`. */
type DialogAction = {
  label: string;
  onPress?: () => void;
  form?: string;
  disabled?: boolean;
  /** Shown instead of the label while the dialog is busy and this action is the one running. */
  busyLabel?: string;
  /** This is the action running while busy (default: the main action). */
  running?: boolean;
};
/** A helper that doesn't close the dialog (Copy, Print): quiet, with its icon, at the left. */
type DialogHelper = { label: string; icon: ReactNode; onPress: () => void };

export function Dialog({ isOpen, onClose, kind, title, children, primary, secondary, cancel, helpers, risky, busy, error, closeLabel }: {
  isOpen: boolean;
  /** Escape, a click outside, the × or the way out (unless `cancel.onPress` says otherwise). */
  onClose: () => void;
  kind: DialogKind;
  /** The question with its object ("Delete case 124?") or the task ("Rename conversation"). */
  title: string;
  children?: ReactNode;
  /** The main action: orange, also when it deletes. */
  primary?: DialogAction;
  /** A second real action (a choice, or a form's second outcome): outlined. */
  secondary?: DialogAction;
  /** The way out: "Cancel" (or "Keep the run" when the main action is itself a cancel). */
  cancel?: { label: string; onPress?: () => void };
  helpers?: DialogHelper[];
  /** Deletes, switches off, resets, cancels: the focus starts on Cancel. */
  risky?: boolean;
  /** While true, nothing closes it and every button is disabled. */
  busy?: boolean;
  /** Why it failed, in the reader's language. */
  error?: ReactNode;
  /** The ×'s name ("Close"); forms and information dialogs. */
  closeLabel?: string;
}) {
  const row = useRef<HTMLDivElement>(null);
  const decides = kind === "confirmation" || kind === "choice";
  const focusCancel = decides && !!risky;
  const focusPrimary = (decides && !risky) || (kind === "information" && !!primary);
  // An information dialog without a main action starts on its ×.
  const focusClose = kind === "information" && !primary;

  // A failure: the focus goes back to the main action (or the way out when there is none).
  useEffect(() => {
    if (!error || !row.current) return;
    (row.current.querySelector<HTMLElement>('[data-dialog-role="primary"]:not([disabled])')
      ?? row.current.querySelector<HTMLElement>('[data-dialog-role="cancel"]'))?.focus();
  }, [error]);

  // Labels too long for one row: the column, at every width. Measured on one row each time.
  useLayoutEffect(() => {
    const el = row.current;
    if (!el || !isOpen) return;
    // The buttons' own widths on one row (a right-aligned row overflows to the left, which scrollWidth
    // doesn't count), plus the gaps between them.
    const fit = () => {
      el.removeAttribute("data-stack");
      const buttons = [...el.children] as HTMLElement[];
      const gap = parseFloat(getComputedStyle(el).columnGap) || 0;
      const needed = buttons.reduce((sum, b) => sum + b.offsetWidth, 0) + gap * Math.max(0, buttons.length - 1);
      if (needed > el.clientWidth + 1) el.setAttribute("data-stack", "");
    };
    fit();
    let width = el.clientWidth;  // only a change of width can change the answer (stacking changes the height)
    const watch = new ResizeObserver(() => { if (el.clientWidth !== width) { width = el.clientWidth; fit(); } });
    watch.observe(el);
    return () => watch.disconnect();
  });

  const label = (a: DialogAction, isMain: boolean) =>
    busy && a.busyLabel && (a.running || (isMain && !secondary?.running)) ? a.busyLabel : a.label;
  const hasRow = !!(primary || secondary || cancel || helpers?.length);
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => { if (!open) onClose(); }} isDismissable={!busy}
                  isKeyboardDismissDisabled={busy} className="ui-modal-overlay">
      <Modal className="ui-modal">
        <AriaDialog className="ui-dialog" role={decides ? "alertdialog" : "dialog"} data-kind={kind}>
          <Heading slot="title" className="ui-dialog-title">{title}</Heading>
          {children}
          {error && <InlineNotice icon={<CircleAlert size={14} />} tone="error" alert className="ui-dialog-error">{error}</InlineNotice>}
          {closeLabel && (kind === "form" || kind === "information") && (
            <IconButton label={closeLabel} onPress={onClose} isDisabled={busy} autoFocus={focusClose} className="ui-dialog-close"><X size={18} aria-hidden /></IconButton>
          )}
          {hasRow && (
            <div className="ui-dialog-actions" ref={row}>
              {helpers?.map((h) => (
                <Button key={h.label} variant="quiet" onPress={h.onPress} isDisabled={busy} data-dialog-role="helper">{h.icon} {h.label}</Button>
              ))}
              {cancel && (
                <Button onPress={cancel.onPress ?? onClose} isDisabled={busy} autoFocus={focusCancel} data-dialog-role="cancel">{cancel.label}</Button>
              )}
              {secondary && (
                <Button type={secondary.form ? "submit" : "button"} form={secondary.form} onPress={secondary.onPress}
                        isDisabled={busy || secondary.disabled} data-dialog-role="secondary">{label(secondary, false)}</Button>
              )}
              {primary && (
                <Button variant="primary" type={primary.form ? "submit" : "button"} form={primary.form} onPress={primary.onPress}
                        isDisabled={busy || primary.disabled} autoFocus={focusPrimary} data-dialog-role="primary">{label(primary, true)}</Button>
              )}
            </div>
          )}
        </AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}

/**
 * A panel that slides over the page from the left, over a scrim (docs/design/chat-ui.md §2, narrow
 * screens): the column as a 320px drawer; from the right, a source (§5). A modal like Dialog: the focus moves in and stays, Escape
 * or a tap on the scrim closes it, and the focus returns to the menu button.
 */
export function Drawer({ isOpen, onClose, label, children, side = "left" }: {
  isOpen: boolean;
  onClose: () => void;
  /** The drawer's accessible name ("Navigation"). */
  label: string;
  children: ReactNode;
  /** right: a panel beside the content on a wide screen, over it on a narrow one (a source, §5). */
  side?: "left" | "right";
}) {
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => { if (!open) onClose(); }} isDismissable className="ui-drawer-overlay">
      <Modal className="ui-drawer" data-side={side}>
        <AriaDialog className="ui-drawer-dialog" aria-label={label}>{children}</AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}
