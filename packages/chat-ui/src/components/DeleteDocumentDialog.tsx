/**
 * Asked when deleting a document that saved conversations cite (suveryn-tracker#12). Its passages are
 * taken out of those conversations either way; the answers still mention facts from it, so the
 * conversations can go too. Keeping them is the default (focused): it is the less destructive choice.
 */
import { AlertCircle, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";

type Props = {
  open: boolean;
  filename: string;
  conversations: number;
  onDelete: (conversations: "clean" | "delete") => Promise<void>;
  onCancel: () => void;
};

export function DeleteDocumentDialog({ open, filename, conversations, onDelete, onCancel }: Props) {
  const m = useT();
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { setError(null); setBusy(false); d.showModal(); }
    if (!open && d.open) d.close();
  }, [open]);

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
    <dialog ref={ref} className="dialog" aria-labelledby="delete-document-title" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2 id="delete-document-title">{m.deleteDocumentDialogTitle(filename)}</h2>
      <p>{m.deleteDocumentDialogBody(conversations)}</p>
      {error && <p className="notice notice-error" role="alert"><AlertCircle size={14} aria-hidden /> {error}</p>}
      <div className="dialog-actions">{/* Keep the conversations first: the dialog focuses it */}
        <button type="button" className="button-primary" onClick={() => choose("clean")} disabled={busy}>
          <Trash2 size={16} aria-hidden /> {m.deleteDocumentKeepConversations}
        </button>
        <button type="button" className="button-secondary" onClick={() => choose("delete")} disabled={busy}>
          {busy ? m.deleting : m.deleteDocumentAndConversations(conversations)}
        </button>
        <button type="button" className="link" onClick={onCancel} disabled={busy}>{m.cancel}</button>
      </div>
    </dialog>
  );
}
