/**
 * Asked when deleting a document that saved conversations cite (suveryn-tracker#12). Its passages are
 * taken out of those conversations either way; the answers still mention facts from it, so the
 * conversations can go too. Keeping them is the main action, the less destructive one; the focus
 * starts on Cancel (docs/design/chat-ui.md, "Dialogs").
 */
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Dialog } from "../ui";

type Props = {
  open: boolean;
  filename: string;
  conversations: number;
  onDelete: (conversations: "clean" | "delete") => Promise<void>;
  onCancel: () => void;
};

export function DeleteDocumentDialog({ open, filename, conversations, onDelete, onCancel }: Props) {
  const m = useT();
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState<"clean" | "delete">("clean");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setBusy(false); } }, [open]);

  const choose = async (what: "clean" | "delete") => {
    setBusy(true);
    setRunning(what);
    setError(null);
    try {
      await onDelete(what);
    } catch (e) {
      setError(m.deleteDocumentFailed(filename, (e as Error).message));
      setBusy(false);
    }
  };

  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} kind="choice" risky title={m.deleteDocumentDialogTitle(filename)} error={error}
            cancel={{ label: m.cancel }}
            secondary={{ label: m.deleteDocumentAndConversations(conversations), onPress: () => void choose("delete"),
                         busyLabel: m.deleting, running: running === "delete" }}
            primary={{ label: m.deleteDocumentKeepConversations, onPress: () => void choose("clean"), busyLabel: m.deleting }}>
      <p>{m.deleteDocumentDialogBody(conversations)}</p>
    </Dialog>
  );
}
