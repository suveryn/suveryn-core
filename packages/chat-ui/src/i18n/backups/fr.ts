/** What the backup service says, in French (formal: vous); the same codes as en.ts. */
import type { BackupMessages } from "./en";

export const backupMessages: BackupMessages = {
  "backup.unavailable": "Le service de sauvegarde de l'appliance n'a pas répondu. Réessayez dans une minute.",
  "backup.busy": "Le service de sauvegarde est encore occupé. Réessayez dans un instant.",
  "backup.share_address_invalid": "Saisissez l'adresse comme \\\\serveur\\partage (SMB) ou serveur:/chemin (NFS).",
  "backup.share_not_local": "Cette adresse n'est pas sur votre propre réseau.",
  "backup.share_unreachable": "L'appliance ne peut pas atteindre ce partage. Vérifiez l'adresse et que le partage autorise cette appliance.",
  "backup.share_login_refused": "Le partage a refusé le nom d'utilisateur ou le mot de passe.",
  "backup.share_not_writable": "Connexion réussie, mais l'appliance ne peut pas y écrire.",
  "backup.disk_gone": "Ce disque n'est plus branché. Cherchez à nouveau.",
  "backup.not_a_key": "Ce n'est pas un fichier de clé de récupération sūveryn.",
  "backup.key_mismatch": "Cette clé n'ouvre pas la sauvegarde. Essayez un autre fichier.",
  "backup.not_found": "Il n'y a pas de sauvegarde sūveryn à cet endroit. Vérifiez le disque ou l'adresse du partage.",
  "backup.damaged": "La sauvegarde la plus récente à cet endroit est endommagée et ne peut pas être restaurée.",
  "backup.version_too_new": "La sauvegarde la plus récente à cet endroit a été faite par une version de sūveryn plus récente que celle de cette appliance. Contactez votre partenaire pour mettre d'abord cette appliance à jour.",
  "backup.settings_invalid": "Les réglages de sauvegarde ne sont pas valides.",
  "backup.target_unreachable": "Le disque ou le partage de sauvegarde était inaccessible.",
  "backup.disk_full": "Le disque de sauvegarde est plein.",
  "backup.link_unsafe": "Un lien dans le dossier des réglages qu'une restauration refuserait. Contactez le support.",
  "backup.verification_failed": "Le disque de sauvegarde n'a pas rendu ce qui y a été écrit (il est peut-être défaillant).",
  "backup.restore_failed": "La restauration s'est arrêtée en cours de route. Choisissez à nouveau la clé de récupération et réessayez ; si elle s'arrête encore, contactez votre partenaire.",
};
