/**
 * Asked when signing out with saved conversations (suveryn-tracker#5): keep them (the default,
 * focused) or delete them all. Escape or Cancel closes the dialog and stays signed in.
 */
import { AlertCircle, LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Button, Dialog, InlineNotice, TextButton } from "../ui";

type Props = { open: boolean; onKeep: () => void; onDelete: () => Promise<void>; onCancel: () => void };

export function SignOutDialog({ open, onKeep, onDelete, onCancel }: Props) {
  const m = useT();
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setDeleting(false); } }, [open]);

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
    <Dialog isOpen={open} onClose={onCancel} busy={deleting} title={m.keepHistoryTitle} actions={<>
      {/* Keep first: the dialog focuses it, and it is the default */}
      <Button variant="primary" autoFocus onPress={onKeep} isDisabled={deleting}><LogOut size={16} aria-hidden /> {m.keepAndSignOut}</Button>
      <Button onPress={remove} isDisabled={deleting}>{deleting ? m.deleting : m.deleteAndSignOut}</Button>
      <TextButton onPress={onCancel} isDisabled={deleting}>{m.cancel}</TextButton>
    </>}>
      <p>{m.keepHistoryBody}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
