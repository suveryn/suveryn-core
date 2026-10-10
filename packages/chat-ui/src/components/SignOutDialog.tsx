/**
 * Asked when signing out with saved conversations (suveryn-tracker#5): keep them (the default,
 * focused) or delete them all. Escape or Cancel closes the dialog and stays signed in.
 */
import { AlertCircle, LogOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";

type Props = { open: boolean; onKeep: () => void; onDelete: () => Promise<void>; onCancel: () => void };

export function SignOutDialog({ open, onKeep, onDelete, onCancel }: Props) {
  const m = useT();
  const ref = useRef<HTMLDialogElement>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { setError(null); d.showModal(); }
    if (!open && d.open) d.close();
  }, [open]);

  const remove = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete();
    } catch (e) {
      setError(m.deleteHistoryFailed((e as Error).message));
      setDeleting(false);
    }
  };

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="signout-title" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2 id="signout-title">{m.keepHistoryTitle}</h2>
      <p>{m.keepHistoryBody}</p>
      {error && <p className="notice notice-error" role="alert"><AlertCircle size={14} aria-hidden /> {error}</p>}
      <div className="dialog-actions">{/* Keep first: the dialog focuses it, and it is the default */}
        <button type="button" className="button-primary" onClick={onKeep} disabled={deleting}>
          <LogOut size={16} aria-hidden /> {m.keepAndSignOut}
        </button>
        <button type="button" className="button-secondary" onClick={remove} disabled={deleting}>
          {deleting ? m.deleting : m.deleteAndSignOut}
        </button>
        <button type="button" className="link" onClick={onCancel} disabled={deleting}>{m.cancel}</button>
      </div>
    </dialog>
  );
}
