/**
 * A modal dialog (suveryn-tracker#44): React Aria's Modal and Dialog. The focus moves into it (give
 * the safe choice, first in `actions`, autoFocus), stays inside while it is open, and returns to where
 * it was when it closes; Escape and a click outside close it, unless it is busy. The page behind can't
 * scroll meanwhile: on iPhone and iPad through the attribute in ui.css (docs/content-security-policy.md,
 * exception 2).
 */
import type { ReactNode } from "react";
import { Dialog as AriaDialog, Heading, Modal, ModalOverlay } from "react-aria-components";

export function Dialog({ isOpen, onClose, title, busy, children, actions }: {
  isOpen: boolean;
  /** Escape, a click outside, or a Cancel button in `actions`. */
  onClose: () => void;
  title: string;
  /** While true (a deletion running), Escape and a click outside don't close it. */
  busy?: boolean;
  children?: ReactNode;
  /** The buttons, stacked, the safe choice first. */
  actions: ReactNode;
}) {
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => { if (!open) onClose(); }} isDismissable={!busy}
                  isKeyboardDismissDisabled={busy} className="ui-modal-overlay">
      <Modal className="ui-modal">
        <AriaDialog className="ui-dialog" role="alertdialog">
          <Heading slot="title" className="ui-dialog-title">{title}</Heading>
          {children}
          <div className="ui-dialog-actions">{actions}</div>
        </AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}

/**
 * A panel that slides over the page from the left, over a scrim (docs/design/sidebar.md §2, narrow
 * screens): the column as a 320px drawer. A modal like Dialog: the focus moves in and stays, Escape
 * or a tap on the scrim closes it, and the focus returns to the menu button.
 */
export function Drawer({ isOpen, onClose, label, children }: {
  isOpen: boolean;
  onClose: () => void;
  /** The drawer's accessible name ("Navigation"). */
  label: string;
  children: ReactNode;
}) {
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => { if (!open) onClose(); }} isDismissable className="ui-drawer-overlay">
      <Modal className="ui-drawer">
        <AriaDialog className="ui-drawer-dialog" aria-label={label}>{children}</AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}
