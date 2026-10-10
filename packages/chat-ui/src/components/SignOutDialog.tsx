/**
 * Asked when signing out with saved conversations (suveryn-tracker#5): keep them (the default,
 * focused) or delete them all. Escape or Cancel closes the dialog and stays signed in.
 */
import { AlertCircle, LogOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Props = { open: boolean; onKeep: () => void; onDelete: () => Promise<void>; onCancel: () => void };

export function SignOutDialog({ open, onKeep, onDelete, onCancel }: Props) {
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
      setError(`Your history couldn't be deleted, so you are still signed in: ${(e as Error).message}`);
      setDeleting(false);
    }
  };

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="signout-title" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2 id="signout-title">Keep your chat history?</h2>
      <p>Your conversations are saved on this server, where only you can see them. Keep them to pick up where you
        left off next time, or delete them now.</p>
      {error && <p className="notice notice-error" role="alert"><AlertCircle size={14} aria-hidden /> {error}</p>}
      <div className="dialog-actions">{/* Keep first: the dialog focuses it, and it is the default */}
        <button type="button" className="button-primary" onClick={onKeep} disabled={deleting}>
          <LogOut size={16} aria-hidden /> Keep and sign out
        </button>
        <button type="button" className="button-secondary" onClick={remove} disabled={deleting}>
          {deleting ? "Deleting…" : "Delete history and sign out"}
        </button>
        <button type="button" className="link" onClick={onCancel} disabled={deleting}>Cancel</button>
      </div>
    </dialog>
  );
}
