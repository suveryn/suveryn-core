/**
 * ChipDialog: a chip that opens a small dialog of choices (the model and its thinking mode,
 * docs/design/chat-ui.md §5). A `DialogTrigger` with a `Popover`, or on a narrow screen a sheet from
 * the bottom with *Done*, as DocumentPicker. The focus moves into the dialog, Escape closes it and the
 * focus returns to the chip; the choices inside apply at once.
 */
import { useState, type ReactNode } from "react";
import { Button as AriaButton, Dialog as AriaDialog, DialogTrigger, Heading, Modal, ModalOverlay, Popover } from "react-aria-components";
import { cx } from "./Button";

export function ChipDialog({ trigger, triggerLabel, title, hideTitle = false, narrow = false, doneLabel, className, children }: {
  /** The chip's content, and its accessible name ("Model and thinking: Qwen3.8-27B, Thorough"). */
  trigger: ReactNode;
  triggerLabel: string;
  /** The dialog's heading. */
  title: string;
  /** The sections inside have their own labels: the heading only names the dialog for a screen reader. */
  hideTitle?: boolean;
  narrow?: boolean;
  doneLabel: string;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const body = (
    <AriaDialog className="ui-chip-dialog">
      <Heading slot="title" className={hideTitle ? "ui-visually-hidden" : "ui-chip-dialog-title"}>{title}</Heading>
      {children}
      {narrow && <AriaButton className="ui-button ui-pick-done" data-variant="primary" onPress={() => setOpen(false)}>{doneLabel}</AriaButton>}
    </AriaDialog>
  );
  return (
    <DialogTrigger isOpen={open} onOpenChange={setOpen}>
      <AriaButton className={cx("ui-pick-trigger", className)} aria-label={triggerLabel}>{trigger}</AriaButton>
      {narrow
        ? <ModalOverlay isDismissable className="ui-sheet-overlay"><Modal className="ui-sheet">{body}</Modal></ModalOverlay>
        : <Popover className="ui-popover ui-chip-popover" placement="top end" offset={8}>{body}</Popover>}
    </DialogTrigger>
  );
}
