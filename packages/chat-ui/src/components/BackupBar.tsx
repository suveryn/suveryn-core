/**
 * Backups need an administrator's attention (review of the backup strategy, 26 October 2026): a bar at the
 * top of the pane, for administrators only, so a failing backup or an untested recovery key isn't noticed
 * only on the Backups page that nobody opens until something is lost (lib/backups.ts backupAttention).
 * It can be put away for this session; it comes back on the next sign-in while the reason stands.
 */
import { DatabaseBackup, X } from "lucide-react";
import { useT } from "../i18n";
import type { BackupAttention } from "../lib/backups";
import { Button } from "../ui";

export function BackupBar({ reason, onOpen, onDismiss }: { reason: BackupAttention; onOpen: () => void; onDismiss: () => void }) {
  const m = useT();
  return (
    <div className="attention-bar" data-serious={reason === "key_due" ? undefined : true}>
      <DatabaseBackup size={18} aria-hidden />
      <p className="attention-bar-text"><strong>{m.backupAttention[reason]}</strong></p>
      <Button size="small" onPress={onOpen}>{m.backupAttentionOpen}</Button>
      <Button variant="plain" className="attention-bar-close" onPress={onDismiss} aria-label={m.close}><X size={16} aria-hidden /></Button>
    </div>
  );
}
