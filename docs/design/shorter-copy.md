# Shorter copy: the built strings

A copy pass over `packages/chat-ui/src/i18n` (at 5bb3408), following the **Short** rule in
chat-ui.md section 1:

- One sentence where one will do, and often none.
- Say the outcome, not the mechanism.
- Don't repeat what the title or the button already says.
- Explain a consequence only when it is irreversible or surprising.

Every "check this" warning stays. They are shorter, but none is dropped.

**How to apply**

- Replace `nl.ts` and `en.ts` with the values below, keeping the template variables as they are.
- Rewrite `fr.ts` from the new English: vous, with a space before a colon.
- An empty value means: show nothing, and remove the element.
- `i18n.test.ts` must still pass.
- The setup's strings (`setup/i18n`) come in a second pass.
- The artboards 01 to 29 already show the new copy.

## Sign-in and errors

| Key | nl | en |
|---|---|---|
| signInCaption | Uw gegevens blijven op deze server. | Your data stays on this server. |
| signInIncomplete | U bent nog niet aangemeld. Open sūveryn via het adres van uw kantoor en sta cookies toe. | You aren't signed in yet. Open sūveryn at your office's address and allow cookies. |
| signInWhenDown | Duurt het langer, vraag dan wie het toestel beheert. | If it lasts, ask whoever manages the appliance. |
| documentsCantBeAdded | Documenten toevoegen kan nu niet. | Documents can't be added right now. |
| historyUnavailable | Gesprekken worden hier niet bewaard. | Conversations aren't kept here. |
| conversationsUnreachable | de gesprekken zijn nu niet bereikbaar; probeer het straks opnieuw | conversations can't be reached; try again shortly |
| tooManyWaiting | te veel documenten in de wachtrij; voeg er straks meer toe | too many documents waiting; add more shortly |
| fileNotSupported | dit bestandstype wordt niet gelezen: gebruik pdf, Word, Excel, Markdown, CSV of .zip | this file type isn't read: use PDF, Word, Excel, Markdown, CSV or .zip |
| conversationTooLong | dit gesprek is te lang; begin een nieuw | this conversation is too long; start a new one |
| databaseUnavailable | de database antwoordt niet; probeer het over een minuut opnieuw | the database isn't answering; try again in a minute |
| signInServiceUnavailable | aanmelden werkt nu niet; probeer het over een minuut opnieuw | sign-in isn't working; try again in a minute |
| offlineKept | | |
| offlineSend | Verzenden kan zodra de server terug is. | You can send once the server is back. |

## Empty states and hints

| Key | nl | en |
|---|---|---|
| emptyIntro | Voeg een document toe en stel er een vraag over. Elk antwoord noemt zijn bron. | Add a document and ask about it. Every answer names its source. |
| firstUseIntro | | |
| caseOnlyDocuments | Antwoorden komen alleen uit dossier ${ref}. | Answers come only from case ${ref}. |
| personalHint | Persoonlijk gesprek | Personal conversation |
| askCardText | Persoonlijk, buiten een dossier. Met een document krijgt u antwoorden met bronnen. | Personal, outside a case. Add a document for answers with sources. |
| caseCardText | Werk samen met uw collega's, met alle documenten en gedeelde gesprekken op één plek. | Work with your colleagues, with all documents and shared conversations in one place. |
| documentsEmpty | Nog geen documenten. | No documents yet. |
| casesEmpty | Nog geen dossiers. | No cases yet. |
| caseEmptyIntro | Stel een vraag over dit dossier. Antwoorden komen uit zijn documenten. | Ask about this case. Answers come from its documents. |
| composerHint | Antwoorden noemen de pagina waarop ze steunen. | Answers name the page they rely on. |
| readingCountsLater | Vragen kan al; documenten tellen mee zodra ze gelezen zijn. | You can ask now; documents count once they're read. |
| attachDocument | Document toevoegen (pdf, Word, Excel, Markdown, CSV, .zip) | Add a document (PDF, Word, Excel, Markdown, CSV, .zip) |
| attachToCase | Document toevoegen aan dossier ${ref} (pdf, Word, Excel, Markdown, CSV, .zip) | Add a document to case ${ref} (PDF, Word, Excel, Markdown, CSV, .zip) |
| passwordWhere | Opent de aanmelding van uw kantoor in een nieuw tabblad. | Opens your office's sign-in in a new tab. |

## Cases

| Key | nl | en |
|---|---|---|
| caseNameHint | Geen naam van een cliënt. | No client names. |
| caseSubjectHint | Bijvoorbeeld een pand of een aanvraagnummer. | For example a property or an application number. |
| accessOfficeHint | Iedereen op het kantoor kan het lezen. | Everyone in the office can read it. |
| addColleagueHint | Lezers lezen; medewerkers voegen ook documenten toe en vragen. | Readers read; contributors also add documents and ask. |
| handOverConfirm | Overdragen aan ${name}? De huidige beheerder blijft medewerker. | Hand over to ${name}? The current manager stays a contributor. |
| readerCantAsk | U kunt dit dossier alleen lezen. | You can only read this case. |
| adminCaseIntro | U bent geen lid: u ziet wie het beheert, niet wat erin zit. | You aren't a member: you see who manages it, not what's in it. |
| adminCasesIntro | Elk dossier met zijn beheerder. De inhoud blijft bij de leden. | Every case with its manager. The content stays with its members. |
| deleteCaseBody | Documenten en gesprekken worden mee verwijderd. Wilt u het bewaren, sluit het dan af. | Its documents and conversations are deleted too. To keep it, close it instead. |
| closeCaseBody | Het blijft leesbaar, maar kan niet meer aangevuld worden. Heropenen kan later. | It stays readable but can't be added to. You can reopen it later. |
| closeCaseKept | Het wordt ${period} na afsluiting verwijderd. | It is deleted ${period} after closing. |
| caseIsClosed | Afgesloten: alleen lezen. | Closed: read only. |
| sharedReadOnly | Gedeeld door ${name}. Begin een eigen gesprek om verder te vragen. | Shared by ${name}. Start your own conversation to ask more. |
| settingsSaved | Opgeslagen. | Saved. |
| casesSummary | ${open} open, ${closed} afgesloten | ${open} open, ${closed} closed |
| conversationsSummary | ${n} gesprekken: ${personal} persoonlijk, ${inCases} in een dossier | ${n} conversations: ${personal} personal, ${inCases} in a case |
| casesFootnote | | |
| conversationsFootnote | Een dossiergesprek zet u vast via zijn dossier. | Pin a case conversation through its case. |
| documentsSummary | ${n} documenten in ${cases} dossiers en uw eigen ruimte | ${n} documents in ${cases} cases and your own space |
| moveHint | Vragen en antwoorden gaan mee, de documenten niet. Alleen u ziet het gesprek tot u het deelt. | The questions and answers move, the documents don't. Only you see it until you share it. |
| moveHintConfidential | Vragen en antwoorden gaan mee, de documenten niet. Alleen u ziet het gesprek. | The questions and answers move, the documents don't. Only you see it. |
| confidentialHint | Alleen leden. Niet te delen. Exports met watermerk. Titels afgeschermd. | Members only. No sharing. Exports watermarked. Titles shielded. |
| notInConfidential | | |
| confidentialRules | Alleen leden · Niet te delen · Exports met watermerk | Members only · No sharing · Exports watermarked |
| confidentialLogged | | |

## Answers and sources

| Key | nl | en |
|---|---|---|
| keepHistoryBody | Uw gesprekken staan op deze server en alleen u ziet ze. Bewaren of verwijderen? | Your conversations are on this server and only you see them. Keep or delete? |
| modelNotLoaded | ${model} wordt geladen. | ${model} is loading. |
| modelLoadsWhenChosen | Laadt wanneer u het kiest | Loads when you choose it |
| statusLoading | ${model} wordt geladen… | ${model} is loading… |
| reasoningNote | Hoe het model redeneerde. Niet gecontroleerd; het antwoord wel. | How the model reasoned. Not checked; the answer is. |
| settingsThinkingHint | Voor nieuwe gesprekken. | For new conversations. |
| answerFailed | Het antwoord mislukte: ${why}. Stel uw vraag opnieuw. | The answer failed: ${why}. Ask again. |
| answerTruncated | Afgebroken: dit antwoord is onvolledig. Vraag naar de rest. | Cut off: this answer is incomplete. Ask for the rest. |
| thoughtTooLong | Het model dacht te lang na. Probeer Snel, of een kleinere vraag. | The model thought too long. Try Fast, or a smaller question. |
| answerStopped | Gestopt. Onvolledig en niet nagekeken. | Stopped. Incomplete and not checked. |
| noSourceCited | Geen bron vermeld. Controleer dit in de documenten. | No source cited. Check this in the documents. |
| notGrounded | Niet uit uw documenten. | Not from your documents. |
| sourceCaption | Zoals gelezen. Controleer de oorspronkelijke pagina. | As read. Check the original page. |
| markedByMeaning | Zelfde betekenis, andere woorden. Controleer het. | Same meaning, other words. Check it. |
| unverifiedTitle | Niet in de documenten en niet berekend. Controleer dit bedrag. | Not in the documents and not calculated. Check this amount. |
| verdictSentence | Nagekeken: staat in de passage | Checked: in the passage |
| verdictSource | Nagekeken: staat in de passage | Checked: in the passage |
| askAboutFine | | |
| chosenGone | De gekozen documenten zijn weg. Antwoorden gebruiken weer het hele dossier. | The chosen documents are gone. Answers use the whole case again. |
| partialRead | Te groot: alleen de best passende passages zijn gelezen. | Too large: only the best-matching passages were read. |
| caseChooseHint | Uw vraag gaat over alle ${n} documenten. Kies er één bij Vraag over. | Your question covers all ${n} documents. Pick one under Ask about. |
| saveToCaseWhat | Als Word-document in dossier ${ref}. Nooit een bron. | As a Word document in case ${ref}. Never a source. |
| exportDisclaimer | Gemaakt door sūveryn. Controleer elk gegeven in de bron. | Made by sūveryn. Check every fact in its source. |
| sourceRemovedCaption | Document verwijderd; de passage is weg. | Document deleted; the passage is gone. |
| deleteDocumentDialogBody | ${n} gesprekken citeren dit document. De passages verdwijnen eruit. | ${n} conversations cite this document. The passages are removed from them. |
| instructionLike | Bron ${…} bevat tekst gericht aan een AI. Die is niet gevolgd; controleer dit antwoord extra. | Source ${…} contains text aimed at an AI. It wasn't followed; check this answer carefully. |
| originLegend | Bron: geüpload, mag geciteerd worden. Gemaakt: door sūveryn, nooit een bron. | Source: uploaded, may be cited. Made: by sūveryn, never a source. |
| notASource | Gemaakt door sūveryn: nooit een bron. | Made by sūveryn: never a source. |

## Document notes

| Key | nl | en |
|---|---|---|
| noteAi | Tekst gericht aan een AI ${pages}. Behandeld als inhoud, nooit als opdracht. | Text aimed at an AI ${pages}. Treated as content, never as an instruction. |
| noteRecovered | Tekst ${pages} zonder opmaak hersteld; tabellen kunnen door elkaar lopen. Controleer met het origineel. | Text ${pages} recovered without layout; tables may run together. Check against the original. |
| noteHeaders | Kop- en voetteksten ${pages} zonder opmaak hersteld. | Headers and footers ${pages} recovered without layout. |

## Playbooks

| Key | nl | en |
|---|---|---|
| playbookIntro | sūveryn zoekt de gegevens in de documenten en toont elk met zijn bron. U bevestigt. | sūveryn finds the facts in the documents and shows each with its source. You confirm. |
| playbookMenuFooter | | |
| playbookNotCovered | Niet gedekt door uw overeenkomst: geen certificering, updates of ondersteuning. | Not covered by your agreement: no certification, updates or support. |
| noDocumentsToRead | Voeg eerst de documenten van het dossier toe. | Add the case's documents first. |
| runErrorInterrupted | Onderbroken door een herstart. Lees opnieuw. | Interrupted by a restart. Read again. |
| runErrorUnreadable | Het resultaat was onleesbaar. Probeer opnieuw of kies het andere model. | The result was unreadable. Try again or choose the other model. |
| runOutOfDateHint | Een gelezen document is sindsdien verwijderd. | A document read here has since been deleted. |
| runSuspiciousSources | Een passage richt zich tot een AI. Kijk deze gegevens extra na. | A passage addresses an AI. Check these facts carefully. |
| checkpointIntro | ${found} van ${total} gevonden. Kijk elk na en bevestig. | ${found} of ${total} found. Check each and confirm. |
| checkpointCaseClosed | Dossier afgesloten. Heropen het om te bevestigen. | Case closed. Reopen it to confirm. |
| wordDisclaimer | Gelezen door sūveryn, bevestigd door een persoon. Controleer voor gebruik. | Read by sūveryn, confirmed by a person. Check before use. |
| adminPlaybooksIntro | Actieve playbooks staan in elk dossier onder de knop Playbook. Uitgeschakelde verdwijnen daar; eerdere runs blijven. | Active playbooks appear in every case under the Playbook button. Switched-off ones disappear there; earlier runs stay. |

## Usage, avatar, backups

| Key | nl | en |
|---|---|---|
| adminMeta | kantoor · appliance | office · appliance |
| playbooksMeta | | |
| usageIntro | Alleen u ziet dit. | Only you see this. |
| adminIntro | | |
| perUserKeptFrom | Per gebruiker vanaf ${date}; daarvoor alleen maandtotalen. | Per user from ${date}; before that, monthly totals only. |
| ownUsageKeptFrom | Vanaf ${date}; daarvoor alleen maandtotalen. | From ${date}; before that, monthly totals only. |
| costExplain | Via een cloud-API ongeveer ${cost}, zonder hardware en stroom. | About ${cost} through a cloud API, without hardware and power. |
| avatarIntro | Uw collega's zien deze foto naast uw naam. | Your colleagues see this photo next to your name. |
| avatarPickHint | PNG, JPEG of WebP. | PNG, JPEG or WebP. |
| avatarFrameHint | Sleep om te verplaatsen; zoom met de schuifregelaar. | Drag to move; zoom with the slider. |
| avatarNotAPicture | Gebruik een PNG-, JPEG- of WebP-bestand. | Use a PNG, JPEG or WebP file. |
| adminBackupsIntro | Elke nacht een versleutelde back-up. Alleen uw herstelsleutel opent ze. | An encrypted backup every night. Only your recovery key opens it. |
| backupsNotSetUp | Geen back-ups ingesteld. Bij een defecte schijf bent u alles kwijt. | No backups set up. If the disk fails, you lose everything. |
| backupsCaption | Back-ups ouder dan de bewaartermijn worden verwijderd; de nieuwste blijft. | Backups older than the keep period are deleted; the newest stays. |
| backupKept | Bewaartermijn | Kept for |
| backupDisk | Vrij op de back-upschijf | Free on the backup disk |
| backupRotate | Een kopie elders: wissel de schijven wekelijks. | A copy elsewhere: swap the disks weekly. |
| backupNewDisk (new) | Nieuwe USB-schijf gevonden: ${model}, ${size}. | New USB disk found: ${model}, ${size}. |
| backupUseSecondDisk (new) | Als extra back-upschijf gebruiken | Use as an extra backup disk |
| keyTestIntro | Test elke drie maanden of uw sleutel de nieuwste back-up opent. Er wordt niets teruggezet. | Every three months, test that your key opens the newest backup. Nothing is restored. |
| keyTesting | Bezig met testen; dit kan enkele minuten duren. | Testing; this can take a few minutes. |
| keyTestOk | Getest op ${when}: de sleutel werkt. | Tested on ${when}: the key works. |
| keyTestDue | Laatst getest op ${when}. Test opnieuw. | Last tested on ${when}. Test again. |
| keyTestFailed | Deze sleutel opent de back-up niet. Probeer een ander bestand. | This key doesn't open the backup. Try another file. |

## The clock on Status (artboard 44, 30 October)

Built in 90cef76; shorter here. French in the handover note
(`Claude outputs/handover-clock-copy-2026-10-30.md`).

| Key | nl | en |
|---|---|---|
| clockKeptByServer | via een tijdserver | via a time server |
| clockByBrowsers | via de browsers | via the browsers |
| clockSetTitle | Klok gelijkzetten? | Set the clock? |
| clockSetBody | Appliance ${appliance} · deze pc ${pc} | Appliance ${appliance} · this PC ${pc} |
| clockSetCheck | Staat deze pc juist? Gesloten dossiers waarvan de termijn dan voorbij is, worden binnen het uur verwijderd. | Is this PC's time right? Closed cases whose keep period has then passed are deleted within the hour. |
| clockSetDone | Klok gelijkgezet. | Clock set. |
| clockSetFailed | Niet gelijkgezet: ${why}. | Not set: ${why}. |

And one change that isn't a string: when the clock is right ("On time"), its detail no longer adds
the seconds ("via the browsers · 2 s behind" becomes "via the browsers").

## New: a second backup disk (artboard 29)

Today a second disk only counts when someone makes a `suveryn-backups` folder on it by hand
(`suveryn-backup`, `_usb`). The folder is the safeguard: without it, any USB stick plugged into the
appliance could be written to. Proposal: keep the safeguard, but let the administrator give
consent from the page instead.

- When a USB disk without the folder is connected, Backups shows "New USB disk found" with
  *Use as an extra backup disk*.
- That button creates `suveryn-backups/` with `.office-recovery-key`, the office's mark. It needs
  an admin endpoint on the gateway and a `prepare` command in `suveryn-backup`.
- A disk marked as another office's is never offered.
