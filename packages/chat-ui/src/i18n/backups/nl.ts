/** What the backup service says, in Dutch (formal: u and uw); the same codes as en.ts. */
import type { BackupMessages } from "./en";

export const backupMessages: BackupMessages = {
  "backup.unavailable": "De back-updienst van de appliance antwoordde niet. Probeer het over een minuut opnieuw.",
  "backup.busy": "De back-updienst is nog bezig. Probeer het zo meteen opnieuw.",
  "backup.share_address": "Vul het adres in zoals \\\\server\\share (SMB) of server:/pad (NFS).",
  "backup.share_not_local": "Dit adres ligt niet op uw eigen netwerk.",
  "backup.share_unreachable": "De appliance kan deze gedeelde map niet bereiken. Controleer het adres en of de gedeelde map deze appliance toelaat.",
  "backup.share_login": "De gedeelde map weigerde de gebruikersnaam of het wachtwoord.",
  "backup.share_write": "Aangemeld, maar de appliance kan er niet schrijven.",
  "backup.disk_gone": "Deze schijf is niet meer aangesloten. Kijk opnieuw.",
  "backup.not_a_key": "Dat is geen herstelsleutelbestand van sūveryn.",
  "backup.wrong_key": "Deze sleutel opent de back-up niet. Probeer een ander bestand.",
  "backup.none_found": "Daar staat geen sūveryn-back-up. Controleer de schijf of het adres van de gedeelde map.",
  "backup.damaged": "De nieuwste back-up daar is beschadigd en kan niet worden teruggezet.",
  "backup.newer_version": "De nieuwste back-up daar is gemaakt door een nieuwere versie van sūveryn dan deze appliance heeft. Neem contact op met uw partner om deze appliance eerst bij te werken.",
  "backup.settings_invalid": "De back-upinstellingen zijn niet geldig.",
  "backup.target_unreachable": "De back-upschijf of gedeelde map was niet bereikbaar.",
  "backup.disk_full": "De back-upschijf is vol.",
  "backup.verify_failed": "De back-upschijf gaf niet terug wat erop werd geschreven (ze is mogelijk defect).",
  "backup.restore_failed": "Het terugzetten stopte halverwege. Kies de herstelsleutel opnieuw en probeer het nog eens; stopt het weer, neem dan contact op met uw partner.",
};
