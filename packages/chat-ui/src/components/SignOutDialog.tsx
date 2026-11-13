/**
 * Asked when signing out with saved conversations (suveryn-tracker#5): keep them (the main action,
 * focused) or delete them all. Escape or Cancel closes the dialog and stays signed in.
 */
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Dialog } from "../ui";

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
      setError(m.deleteHistoryFailed({ why: (e as Error).message }));
      setDeleting(false);
    }
  };

  return (
    <Dialog isOpen={open} onClose={onCancel} busy={deleting} kind="choice" title={m.keepHistoryTitle} error={error}
            cancel={{ label: m.cancel }}
            secondary={{ label: m.deleteAndSignOut, onPress: () => void remove(), busyLabel: m.deleting, running: true }}
            primary={{ label: m.keepAndSignOut, onPress: onKeep }}>
      <p>{m.keepHistoryBody}</p>
    </Dialog>
  );
}
