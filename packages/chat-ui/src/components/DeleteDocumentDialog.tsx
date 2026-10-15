/**
 * Asked when deleting a document that saved conversations cite (suveryn-tracker#12). Its passages are
 * taken out of those conversations either way; the answers still mention facts from it, so the
 * conversations can go too. Keeping them is the default (focused): it is the less destructive choice.
 */
import { AlertCircle, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Button, Dialog, InlineNotice, TextButton } from "../ui";

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
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setBusy(false); } }, [open]);

  const choose = async (what: "clean" | "delete") => {
    setBusy(true);
    setError(null);
    try {
      await onDelete(what);
    } catch (e) {
      setError(m.deleteDocumentFailed(filename, (e as Error).message));
      setBusy(false);
    }
  };

  return (
    <Dialog isOpen={open} onClose={onCancel} busy={busy} title={m.deleteDocumentDialogTitle(filename)} actions={<>
      {/* Keep the conversations first: the dialog focuses it */}
      <Button variant="primary" autoFocus onPress={() => choose("clean")} isDisabled={busy}>
        <Trash2 size={16} aria-hidden /> {m.deleteDocumentKeepConversations}
      </Button>
      <Button onPress={() => choose("delete")} isDisabled={busy}>
        {busy ? m.deleting : m.deleteDocumentAndConversations(conversations)}
      </Button>
      <TextButton onPress={onCancel} isDisabled={busy}>{m.cancel}</TextButton>
    </>}>
      <p>{m.deleteDocumentDialogBody(conversations)}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
