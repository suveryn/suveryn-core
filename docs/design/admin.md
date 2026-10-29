# Administration

The spec for *Administration* in the chat UI (`packages/chat-ui`): what an administrator manages for
the office and the appliance, drawn on artboards 26 to 43 of the design canvas. Split from
`sidebar.md` (now [chat-ui.md](chat-ui.md)) on 28 October 2026. The colour and copy rules of
chat-ui.md section 1 apply here; this file only adds what is particular to *Administration*.

This file says how things are to be **now**; where an artboard and this file disagree, this file
wins. Interface text is quoted in English, with Dutch and French under *Strings*.

## The pages

From the build chat's brief (27 October) and Filip's decisions the same day: a side menu, nothing is
ever blocked by the support agreement, no scheduled install, and updates never uploaded through the
browser. Artboards 26 to 29 are what is built (with tabs); 30 to 43 are the design.

**A side menu in two groups** replaces the tabs, which no longer fit:

- *Office*: Users, Cases, Playbooks, Usage, Settings.
- *Appliance*: Status, Updates and models, Backups, Network, Licence.
- A triangle beside an item that needs attention, a download icon beside *Updates and models* when
  an update is ready. *Status* opens first.
- Narrow screens (42): the menu becomes the first page, a list with the same groups; every page has
  a back arrow to it. Tables become lists, row menus and dialogs become sheets, targets 44 px.

**Status** (30): plain words, no product names.

- *Needs attention*, only when something does, each with the button that fixes it.
- *Is everything working?*: answering questions (the model), reading documents, signing in
  (Keycloak), keeping your data (the database), disk space. A teal check with "Working", or an ink cross
  with "Not working since 09:12" and what still works (39).
- An overview: version, last backup, users against the agreement, support.

**Users** (32, 34): manages accounts through Keycloak's admin API, so nobody needs its console.

- The list: name and e-mail, administrator or not, last sign-in, account on or off. "12 of 15
  users" from the manifest's `users`; without a manifest, "12 users". Accounts that are off don't
  count.
- *Add user* (the page's one orange button): name, e-mail, administrator or not. **The appliance
  sends no e-mail** (no mail server, maybe air-gapped), so adding shows a temporary password once,
  with the address and an expiry, to pass on (Keycloak `temporary`, `UPDATE_PASSWORD`). The person
  chooses a password and sets up two-step sign-in at first sign-in.
- The row menu: make administrator or remove the rights; have the password set again (a new
  temporary password, as above); have two-step sign-in set again; sign out everywhere; switch the
  account off, or on again.
- **Switching off someone who manages cases** hands each case over inside the dialog, showing only
  the case's reference and name. The button waits until every case has a new manager: the one
  thing that can't be done. The person stays a member.
- **Always one administrator**: the menu item is disabled with the reason under it ("You are the
  only administrator…"), not an error afterwards. Removing your own rights says that
  *Administration* closes for you.
- **More users than agreed** shows a triangle by the count and one sentence in the add dialog.
  Adding still works.
- *Sign-ins and changes*: Keycloak's sign-in and admin events in plain words, kept 180 days.
- **Through Keycloak's admin REST API**, called by the gateway with a service-account client
  (`manage-users`, `view-users`, `view-events`), never by the browser:
  - list: `GET /users`; last sign-in from the `LOGIN` events (Keycloak keeps no such field);
  - add: `POST /users` with `requiredActions` `UPDATE_PASSWORD` and `CONFIGURE_TOTP`, then
    `PUT /users/{id}/reset-password` with `temporary: true`;
  - administrator: realm role `suveryn-admin` through `/users/{id}/role-mappings/realm`;
  - off or on: `PUT /users/{id}` with `enabled`;
  - reset password: `reset-password`, temporary; reset two-step: delete the `otp` credential and add
    `CONFIGURE_TOTP`;
  - sign out everywhere: `POST /users/{id}/logout`;
  - events: `GET /events` and `GET /admin-events`.
  The gateway enforces "always one administrator" and the case hand-over before switching off. This
  replaces a separate *Activity* page. Nothing from inside a case.

**Settings** (35): what the office decides, in one place. Who sees a case, how long closed
cases and conversations are kept, and the rates for the indicative cost. *Cases* and *Usage* then
only show these, with "Change in Settings". *Save* is active after a change, and a shorter keep
period asks for confirmation with the number of cases or conversations that will go.

- *Who sees a case* applies to new cases or, by choice, to all cases. *All cases* asks for
  confirmation with the count ("38 cases become visible to everyone in the office"). Strictly
  confidential cases never change with it; their members decide.

**Backups** (36) become editable here, not in Settings: they belong with the backup's status and
test.

- *Back up now* (primary), with "Next: tonight at 02:00." beside it. A backup closes nobody out.
- *Every day at*: the time of the daily run, 02:00 by default, in whole hours.
- No "last failed" card (built on 29): a failure of the latest run shows in *Last backup* and on *Status*; an older one is history.
- The target after setup: USB disk (the detected disk) or network share (SMB or NFS: address,
  user, password, *Test connection*), with the setup's cards, fields and strings. Old backups stay
  where they were.
- Retention: 14, 30, 90 days or 1 year.
- **The recovery sheet**: the appliance holds only the public half of the key, so it can never
  print the key. *Print the recovery sheet* prints what it knows (appliance name and ID, where the
  backups are, the key's fingerprint, the restore steps) and a box "Key kept at:" (39). *Make a new
  recovery key…* creates one in the browser, as setup does; only then can the sheet be printed once
  with the key. Older backups still need the old key, and the confirmation says so.

**Licence and support** (37): what differs from the agreement first (more users than agreed, a
missed check-in, an expiry), each in ink with a way out, and "Nothing is blocked". Then the
agreement from the manifest (edition, users, valid until, next check-in), the QR code for the
quarterly check-in, the appliance ID and key fingerprint with *Copy*, and the manifest drop zone.
Uploading the manifest in the browser is fine: it is a small text file, checked on the appliance,
with the setup's four errors.

**Updates and models** (33, 38, 41), depending on #40, which isn't built: until it is, the page
shows the version and the models only.

- Connected: the appliance downloads by itself. Air-gapped: a USB stick plugged into the appliance,
  which the page finds as *Backups* finds a disk. Never an upload in the browser. Either way the
  signature is checked first; a bad one says nothing was installed.
- "New in 1.5.0" comes from the signed bundle itself, in en, nl and fr, so an air-gapped office
  sees it as soon as the stick is found and checked. Without a stick, an air-gapped appliance doesn't
  know a new version exists.
- The administrator chooses when: *Install now…* confirms with what happens (a fresh backup, about
  20 minutes, everyone can still work; then everyone is signed out for about 15 minutes; a restart)
  and who is signed in now. No scheduled install.
- Sign-in shows "sūveryn is being updated. You can sign in again around 11:20."
- If the new version doesn't come up healthy, the appliance goes back by itself and says so, naming
  which check of *Status* failed ("Reading documents didn't work"); details are in the log. If the backup first fails, nothing is installed: impossible, so it blocks.
- **Expired support doesn't block an update**: the page says it and installs anyway.
- *Models*: the list, the default, and *Load model bundle* from a USB stick.

**Network** (31): not in the brief, but setup promises "you can change this later in the admin
dashboard". Name and address read-only (console option 2); connected or air-gapped; outgoing to
approved destinations only or everything; sūveryn's destinations locked, the office's own
removable; the daily check.

**Playbooks** (28), as built:

- The list: name, id, version, pack, covered or not.
- An *Active* switch per playbook (`playbook_settings`, `GET /v1/admin/playbooks`,
  `PUT /v1/admin/playbooks/{slug} {active}`).
  - An inactive playbook leaves the composer's menu, and starting it answers 404.
  - Runs already made stay readable.

**Creating a playbook** (an office's own: name, case types, facts, instructions, labels in nl, fr
and en) is wanted, but it pulls the manifest and pack format forward (platform.md). An office
playbook is never covered.

**Charts on Usage** (26) use the chart palette (chat-ui.md section 1): input violet, output ochre; per kind
violet, ochre, sky blue.

**Privacy on every one of these screens**: an administrator who isn't a member of a case sees only
its reference and name. Counts, never content.

**States** (39): loading as `surface-alt` shapes with `aria-busy`; errors as what failed, what
follows, and one way out; empty states as one sentence and the action that fixes it. Dark: 40 and
41 (dialogs on `surface-alt` with a `line` ring in the dark theme).

## Strings (artboard 43)

English, Dutch and French. The setup's strings are reused as they are and not repeated: `usbDisk`, `networkShare`, `keepFor`, `keepHint`, `recoveryKey`, `keyFingerprint`, `dropManifest`, `manifestHint`, `nextCheckIn`, `noManifest`, `laterTitle`, `applianceId`, `testConnection`.

| English | Dutch | French |
|---|---|---|
| **Menu** | | |
| Office | Kantoor | Cabinet |
| Appliance | Appliance | Appliance |
| Users | Gebruikers | Utilisateurs |
| Settings | Instellingen | Paramètres |
| Status | Status | État |
| Updates and models | Updates en modellen | Mises à jour et modèles |
| Network | Netwerk | Réseau |
| Licence | Licentie | Licence |
| Licence and support | Licentie en ondersteuning | Licence et assistance |
| Needs attention | Vraagt aandacht | À vérifier |
| Update available | Update beschikbaar | Mise à jour disponible |
| **Status** | | |
| Is everything working? | Werkt alles? | Tout fonctionne ? |
| Overview | Overzicht | Vue d'ensemble |
| Answering questions | Vragen beantwoorden | Réponses aux questions |
| Reading documents | Documenten lezen | Lecture des documents |
| Signing in | Aanmelden | Connexion |
| Keeping your data | Gegevens bewaren | Conservation des données |
| Disk space | Schijfruimte | Espace disque |
| Working | Werkt | Fonctionne |
| Enough | Genoeg | Suffisant |
| Not working since {time} | Werkt niet sinds {time} | En panne depuis {time} |
| {n} in progress | {n} bezig | {n} en cours |
| {n} waiting | {n} in de wachtrij | {n} en attente |
| {n} signed in | {n} aangemeld | {n} connectés |
| {free} free of {total} | {free} vrij van {total} | {free} libres sur {total} |
| Checked at {time}. | Gecontroleerd om {time}. | Vérifié à {time}. |
| Questions about documents already read still work. | Vragen over gelezen documenten werken gewoon. | Les questions sur les documents déjà lus fonctionnent. |
| Status unavailable. | Status niet beschikbaar. | État indisponible. |
| Trying again in a minute. | Nieuwe poging over een minuut. | Nouvel essai dans une minute. |
| Try again | Opnieuw proberen | Réessayer |
| **Users** | | |
| Add user | Gebruiker toevoegen | Ajouter un utilisateur |
| Search by name or e-mail | Zoek op naam of e-mail | Rechercher par nom ou e-mail |
| {n} of {max} users | {n} van {max} gebruikers | {n} utilisateurs sur {max} |
| Administrator | Administrator | Administrateur |
| Last signed in | Laatst aangemeld | Dernière connexion |
| Account | Account | Compte |
| On | Aan | Activé |
| Off | Uit | Désactivé |
| never | nog nooit | jamais |
| Make administrator | Administrator maken | Nommer administrateur |
| Remove administrator rights | Administratorrechten intrekken | Retirer les droits d'administrateur |
| Remove rights | Rechten intrekken | Retirer les droits |
| Reset password | Wachtwoord opnieuw instellen | Réinitialiser le mot de passe |
| Reset two-step sign-in | Tweestapsaanmelding opnieuw instellen | Réinitialiser la connexion en deux étapes |
| Sign out everywhere | Overal afmelden | Déconnecter partout |
| Switch account off… | Account uitschakelen… | Désactiver le compte… |
| Switch account on | Account inschakelen | Activer le compte |
| Can open Administration. | Kan Beheer openen. | Peut ouvrir l'administration. |
| You get a temporary password to pass on. | U krijgt een tijdelijk wachtwoord om door te geven. | Vous recevez un mot de passe temporaire à transmettre. |
| Pass this on to {name} | Geef dit door aan {name} | Transmettez ceci à {name} |
| Temporary password | Tijdelijk wachtwoord | Mot de passe temporaire |
| You see it only once. | U ziet het maar één keer. | Vous ne le voyez qu'une fois. |
| Switch {name} off? | {name} uitschakelen? | Désactiver {name} ? |
| Choose who takes over their {n} cases. | Kies wie haar {n} dossiers overneemt. | Choisissez qui reprend ses {n} dossiers. |
| Choose someone | Kies iemand | Choisir quelqu'un |
| Their conversations and documents stay. | Haar gesprekken en documenten blijven. | Ses conversations et documents restent. |
| Hand over and switch off | Overdragen en uitschakelen | Transférer et désactiver |
| They can no longer open Administration. | Hij kan Beheer dan niet meer openen. | Il ne pourra plus ouvrir l'administration. |
| Administration closes for you. | Beheer sluit dan voor u. | L'administration se ferme pour vous. |
| Not possible: you are the only administrator. | Kan niet: u bent de enige administrator. | Impossible : vous êtes le seul administrateur. |
| Not possible for your own account. | Kan niet voor uw eigen account. | Impossible pour votre propre compte. |
| Their current password stops working. You get a temporary password to pass on. | Haar huidige wachtwoord vervalt. U krijgt een tijdelijk wachtwoord om door te geven. | Son mot de passe actuel ne fonctionne plus. Vous recevez un mot de passe temporaire à transmettre. |
| They set it up again at their next sign-in. | Bij de volgende aanmelding stelt ze die opnieuw in. | Elle la reconfigure à sa prochaine connexion. |
| On all their devices. They can sign in again straight away. | Op al haar toestellen. Ze kan zich meteen weer aanmelden. | Sur tous ses appareils. Elle peut se reconnecter aussitôt. |
| This will be user {n}; your agreement covers {max}. | Dit wordt de {n}e gebruiker; uw overeenkomst telt er {max}. | Ce sera le {n}e utilisateur ; votre contrat en prévoit {max}. |
| Accounts that are off don't count. | Uitgeschakelde accounts tellen niet mee. | Les comptes désactivés ne comptent pas. |
| Sign-ins and changes | Aanmeldingen en wijzigingen | Connexions et modifications |
| Kept 180 days. | Bewaard 180 dagen. | Conservé 180 jours. |
| Users couldn't be loaded. | Gebruikers niet geladen. | Utilisateurs non chargés. |
| You are the only user. | U bent de enige gebruiker. | Vous êtes le seul utilisateur. |
| **Settings** | | |
| Who sees a case | Wie ziet een dossier | Qui voit un dossier |
| New cases | Nieuwe dossiers | Nouveaux dossiers |
| All cases | Alle dossiers | Tous les dossiers |
| Strictly confidential cases stay with their members. | Strikt vertrouwelijke dossiers blijven alleen voor de leden. | Les dossiers strictement confidentiels restent réservés à leurs membres. |
| Members only | Alleen de leden | Les membres uniquement |
| Everyone in the office | Iedereen op het kantoor | Tout le cabinet |
| Can be changed per case. | Per dossier aan te passen. | Modifiable par dossier. |
| {n} cases become visible to everyone in the office. | {n} dossiers worden zichtbaar voor iedereen op het kantoor. | {n} dossiers deviennent visibles pour tout le cabinet. |
| Keep a closed case | Een gesloten dossier bewaren | Conserver un dossier clôturé |
| Then it is deleted with everything in it. | Daarna wordt het met alle inhoud verwijderd. | Il est ensuite supprimé avec tout son contenu. |
| Keep conversations | Gesprekken bewaren | Conserver les conversations |
| From the last change. | Vanaf de laatste wijziging. | À partir de la dernière modification. |
| Until someone deletes it | Tot iemand het verwijdert | Jusqu'à sa suppression |
| Indicative cost | Indicatieve kost | Coût indicatif |
| For the comparison on Usage. | Voor de vergelijking op Verbruik. | Pour la comparaison dans Utilisation. |
| Change in Settings | Wijzigen in Instellingen | Modifier dans Paramètres |
| Applies to | Geldt voor | S'applique à |
| {n} cases become visible to their members only. | {n} dossiers worden alleen nog zichtbaar voor de leden. | {n} dossiers ne sont plus visibles que par leurs membres. |
| {n} saved conversations will be deleted. | {n} bewaarde gesprekken worden verwijderd. | {n} conversations enregistrées seront supprimées. |
| Save the settings? | Instellingen opslaan? | Enregistrer les paramètres ? |
| Settings couldn't be loaded. | Instellingen niet geladen. | Paramètres non chargés. |
| **Backups** | | |
| Back up now | Nu een back-up maken | Sauvegarder maintenant |
| Where the backups are | Waar de back-ups staan | Emplacement des sauvegardes |
| Next: tonight at 02:00. | Volgende: vannacht om 02:00. | Prochaine : cette nuit à 02:00. |
| Every day at | Elke dag om | Chaque jour à |
| Retention | Bewaartermijn | Durée de conservation |
| Address | Adres | Adresse |
| Reachable | Bereikbaar | Accessible |
| Older backups stay on the USB disk. | Oude back-ups blijven op de USB-schijf. | Les anciennes sauvegardes restent sur le disque USB. |
| Print the recovery sheet | Herstelblad afdrukken | Imprimer la fiche de récupération |
| Make a new recovery key… | Nieuwe herstelsleutel maken… | Créer une nouvelle clé de récupération… |
| The recovery key is not on this sheet. It is the .txt file from the installation. | De herstelsleutel staat niet op dit blad. Het is het .txt-bestand van de installatie. | La clé de récupération ne figure pas sur cette fiche. C'est le fichier .txt de l'installation. |
| Key kept at: | Sleutel bewaard op: | Clé conservée à : |
| Set up backups | Back-ups instellen | Configurer les sauvegardes |
| If the disk fails, you lose everything. | Bij een defecte schijf bent u alles kwijt. | Si le disque tombe en panne, vous perdez tout. |
| **Licence** | | |
| Differs from your agreement | Wijkt af van uw overeenkomst | S'écarte de votre contrat |
| {n} users; the agreement covers {max}. | {n} gebruikers, de overeenkomst telt er {max}. | {n} utilisateurs ; le contrat en prévoit {max}. |
| Switch an account off or ask your partner for more. | Schakel een account uit of vraag uw partner om meer. | Désactivez un compte ou demandez-en plus à votre partenaire. |
| The check-in of {date} hasn't happened. | De check-in van {date} is niet gebeurd. | Le check-in du {date} n'a pas eu lieu. |
| Scan the QR code below. | Scan de QR-code hieronder. | Scannez le code QR ci-dessous. |
| Go to Users | Naar Gebruikers | Vers Utilisateurs |
| Nothing is blocked. | Er wordt niets geblokkeerd. | Rien n'est bloqué. |
| Agreement | Overeenkomst | Contrat |
| Edition | Editie | Édition |
| Valid until | Geldig tot | Valable jusqu'au |
| Scan with your phone. Upload the manifest you get back below. | Scan met uw telefoon. Laad het manifest dat u terugkrijgt hieronder op. | Scannez avec votre téléphone. Déposez ci-dessous le manifeste reçu. |
| Copy ID and fingerprint | ID en vingerafdruk kopiëren | Copier l'identifiant et l'empreinte |
| After 14 days everyone sees a notice. | Na 14 dagen ziet iedereen een melding. | Après 14 jours, tout le monde voit un avis. |
| This manifest belongs to another appliance. | Dit manifest hoort bij een andere appliance. | Ce manifeste appartient à une autre appliance. |
| **Updates** | | |
| Installed | Geïnstalleerd | Installée |
| Ready to install | Klaar om te installeren | Prête à installer |
| Downloading | Wordt gedownload | Téléchargement en cours |
| On the USB stick | Op de USB-stick | Sur la clé USB |
| Signature checked | Handtekening gecontroleerd | Signature vérifiée |
| What happens | Wat er gebeurt | Ce qui se passe |
| Install now… | Nu installeren… | Installer maintenant… |
| Install | Installeren | Installer |
| Choose a quiet moment. | Kies een rustig moment. | Choisissez un moment calme. |
| A backup first. If it fails, nothing happens. | Eerst een back-up. Mislukt die, dan gebeurt er niets. | D'abord une sauvegarde. Si elle échoue, rien ne se passe. |
| Everyone is signed out for about 15 minutes. | Iedereen wordt ongeveer 15 minuten afgemeld. | Tout le monde est déconnecté pendant environ 15 minutes. |
| The appliance restarts. Your data stays. | De appliance herstart. Uw gegevens blijven. | L'appliance redémarre. Vos données restent. |
| If {version} doesn't start properly, {previous} comes back by itself. | Start {version} niet goed, dan keert {previous} vanzelf terug. | Si {version} ne démarre pas correctement, {previous} revient d'elle-même. |
| Plug the USB stick with the update into the appliance. | Steek de USB-stick met de update in de appliance. | Branchez la clé USB contenant la mise à jour sur l'appliance. |
| Invalid signature. Nothing was installed. | Handtekening ongeldig. Er is niets geïnstalleerd. | Signature invalide. Rien n'a été installé. |
| Ask your partner for a new stick. | Vraag uw partner om een nieuwe stick. | Demandez une nouvelle clé à votre partenaire. |
| Signed in now: {names}. | Nu aangemeld: {names}. | Connectés maintenant : {names}. |
| After the restart this page reloads by itself. | Na de herstart laadt deze pagina vanzelf opnieuw. | Après le redémarrage, cette page se recharge d'elle-même. |
| sūveryn is being updated. You can sign in again around {time}. | sūveryn wordt bijgewerkt. Aanmelden kan weer rond {time}. | sūveryn est en cours de mise à jour. Reconnexion possible vers {time}. |
| Updated to {version} at {time}. | Bijgewerkt naar {version} om {time}. | Mise à jour vers {version} à {time}. |
| {version} didn't start properly; {previous} is running again. | {version} startte niet goed; {previous} draait weer. | {version} n'a pas démarré correctement ; {previous} fonctionne de nouveau. |
| {check} didn't work. Nothing was lost. | {check} werkte niet. Er is niets verloren. | {check} ne fonctionnait pas. Rien n'a été perdu. |
| Not installed: the backup failed. | Niet geïnstalleerd: de back-up mislukte. | Non installée : la sauvegarde a échoué. |
| Support ended on {date}. You can still install. | Ondersteuning verlopen op {date}. Installeren kan toch. | Assistance expirée le {date}. Vous pouvez tout de même installer. |
| From a USB stick. The signature is checked first. | Van een USB-stick. De handtekening wordt eerst gecontroleerd. | Depuis une clé USB. La signature est vérifiée d'abord. |
| Load model bundle | Modelbundel laden | Charger un paquet de modèles |

## Decided (Filip, 28 October)

- **Nothing is blocked by the agreement**, updates and model bundles included. appliance-architecture.md
  (suveryn-appliance) and the setup's `skipNote` now say so.
- **Everyone sees the notice**: without a manifest after 14 days, every deviation from the agreement,
  and again when support ends.
- **The certificate's expiry** appears on *Status* when it nears (with #41's work, suveryn-tracker).
- **The dark theme waits**: the chat UI has none yet, so the dark artboards aren't built.
- The update durations (20 and 15 minutes) stay estimates for #40 to confirm, and the place on
  suveryn.com where an appliance learns of a new version isn't designed yet.

## Built so far

- The side menu (and the narrow list) with *Status*, and the existing *Cases*, *Playbooks*, *Usage* and
  *Backups*; the other items join as their pages are built. *Status* reads `GET /v1/admin/status` (the
  gateway checks every minute, so "since" is when a failure began); the overview shows the version when
  the appliance has one (its release and the core commit, or `SUVERYN_VERSION`; Filip, 29 October), and the
  last backup. Users against the agreement and support join
  with *Licence*. A full disk says "Almost full" (a string the table didn't have).
- *Users*, as the administrator who is signed in (Filip, 28 October: no extra client; the gateway's
  README). Built as drawn, with these
  differences: the temporary password has no expiry (Filip, 28 October: Keycloak is the password
  manager and can't expire one password; it works until its first use, and one never used shows as
  "never" signed in), so the pass-on dialog has no "Valid until"; *Sign-ins and changes* takes the changes from Keycloak's
  admin events, which name the administrator but hold no details, so switching an account off or on reads
  as "Account changed"; the dialog titles, the event lines and the filter
  needed strings the table didn't have; the Dutch and French texts that named a person "haar", "hij",
  "ze", "il" or "elle" (drawn for one example person) use the name or "de" instead, since an account
  has no known gender; the "Advanced: open Keycloak" link isn't built, as nobody should need it.
- *Settings*: who sees a case, the two keep periods and the indicative cost's rates, one *Save* for all;
  *Cases* and *Usage* only show them, with "Change in Settings". Differences: "New cases" keeps the
  existing cases with their members by restricting those that followed the default (the case model has no
  other way to hold "as it was"); "All cases" also opens cases a manager restricted, as drawn, with a line
  in each access log; closing to the members needs no choice (it applies to every case that follows the
  default) but is confirmed with its count too; a shorter period for closed cases deletes nothing at once
  (it applies to cases closed from then on, cases.md), so only conversations are counted. New strings:
  "Applies to", "Save the settings?", the counts of cases closed and conversations deleted, and "Settings
  couldn't be loaded.".

- *Backups*, editable: *Back up now* with when the next one runs, where (the USB disk, or a share whose
  *Test connection* now signs in and writes a test file: the setup's only saw whether the server answered),
  *Every day at* (whole hours, 02:00 by default) and *Retention* with one *Save*, and the recovery sheet
  with *Make a new recovery key…*. The gateway can't change the appliance's backups itself: each change is
  a request its backup service checks as the setup does (suveryn-appliance `backup/README.md`). Since /etc
  is read-only, the hour is in the backup settings and the timer runs hourly. Differences: the sheet shows
  the appliance's address, not its ID (that comes with the manifest, #41), and the key's fingerprint is
  its public half shortened, as on the key file's "public key" line; the existing status and the key test
  stay as they were, so a failure still shows in the notice at the top. New strings: "Started.", "Backing
  up since…", "Next: today/tomorrow at…", "Leave empty to keep the saved password.", "Saved. The next
  backup uses these settings.", the backup service not answering, the new key's dialog, the sheet's
  labels and restore steps, the share test's "login" and "write" refusals, and its success ("Connected:
  signed in, and a test file written and removed.": the setup's own says signing in is checked at the
  first backup, which is no longer so here).

## History

- **27 October**: designed from the build chat's brief: a side menu, *Users*, *Settings*, editable
  *Backups*, *Licence and support*, *Updates and models*, *Status*, with their states, dark and
  narrow versions and the strings in three languages (artboards 30 to 43).
- **28 October**: review with Filip: shorter copy throughout, the backup schedule on *Backups*,
  *Who sees a case* for new or all cases, the last-administrator menu with its row, teal for system
  statuses and orange text actions, one notice box; split from `sidebar.md` into this file.
