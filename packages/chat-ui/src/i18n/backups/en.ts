/**
 * What the backup service says, in English: the registry's `backup` area. Two screens word these codes, Administration ›
 * Backups and the appliance's web setup (a restore), so the sentences are here once and both tables take them; the
 * setup says a few its own way (setup/i18n/en.ts). This table defines them; nl.ts and fr.ts must have the same.
 */
import type { BackupCode } from "../../lib/messages";

export const backupMessages = {
  "backup.unavailable": "The appliance's backup service didn't answer. Try again in a minute.",
  "backup.busy": "The backup service is still busy. Try again in a moment.",
  "backup.share_address_invalid": "Enter the address like \\\\server\\share (SMB) or server:/path (NFS).",
  "backup.share_not_local": "This address isn't on your own network.",
  "backup.share_unreachable": "The appliance can't reach this share. Check the address and that the share allows this appliance.",
  "backup.share_login_refused": "The share refused the user name or password.",
  "backup.share_not_writable": "Signed in, but the appliance can't write there.",
  "backup.disk_gone": "This disk isn't plugged in any more. Look again.",
  "backup.not_a_key": "That isn't a sūveryn recovery key file.",
  "backup.key_mismatch": "This key doesn't open the backup. Try another file.",
  "backup.not_found": "There is no sūveryn backup there. Check the disk or the share's address.",
  "backup.damaged": "The newest backup there is damaged and can't be restored.",
  "backup.version_too_new": "The newest backup there was made by a newer version of sūveryn than this appliance has. Contact your partner to update this appliance first.",
  "backup.settings_invalid": "The backup settings aren't valid.",
  "backup.target_unreachable": "The backup disk or share couldn't be reached.",
  "backup.disk_full": "The backup disk is full.",
  "backup.link_unsafe": "A link in the settings folder that a restore would refuse. Ask support.",
  "backup.verification_failed": "The backup disk didn't give back what was written (it may be failing).",
  "backup.restore_failed": "The restore stopped partway. Enter the recovery key again and try again; if it stops again, contact your partner.",
} satisfies Record<BackupCode, string>;

export type BackupMessages = Record<keyof typeof backupMessages, string>;
