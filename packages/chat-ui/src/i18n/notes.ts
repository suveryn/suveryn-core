/**
 * Notes for the translator of the chat's text (the handbook's decision of 13 November 2026, rule 4; docs/translations.md):
 * where an entry appears and what its values stand for. Written in English, beside the English text, by the same keys;
 * TypeScript refuses a note for an entry that doesn't exist. An entry that chooses by a word (`select`) must have one,
 * since the words it chooses by are the software's, not the reader's. The export hands each note to the translator's
 * tool with its sentence (suveryn-tracker#148).
 */
import type en from "./en";
import type { Notes } from "./message";

/** What a value's name means wherever it is used, so an entry needs no note for it. */
export const valueNotes: Record<string, string> = {
  why: "A whole sentence saying what went wrong, taken from the tables 'messages', 'messageAreas' or 'messageKinds'. It starts with a capital and ends with a full stop; put it after a full stop, never after a colon.",
  count: "How many items the list beside it has; only used to choose singular or plural, never shown.",
  pages: "Page numbers as text, already joined the way the language does it: \"4\", \"2 and 7\", \"2, 5 and 7\".",
  figures: "Figures from an answer as text, already joined the way the language does it: \"1.000,00 and 2,5\".",
  sources: "Source numbers as text, already joined the way the language does it: \"2 and 6\".",
  n: "A count, or a source's number where the sentence says \"source {n}\".",
  file: "A document's file name, as uploaded: \"deed.pdf\".",
  name: "A person's name.",
  ref: "A reference: a case's (\"2026/0611\") or, for a failure, the code the administrator finds in the log (\"7F3K-92QD\").",
  reference: "A case's reference: \"2026/0611\".",
  date: "A date, already written in the reader's language.",
  day: "A day, already written in the reader's language: \"today\", \"3 Oct\".",
  time: "A time or date, already written in the reader's language.",
  when: "A moment, already written in the reader's language: \"Today\", \"3 Oct\".",
};

export const notes: Notes<typeof en> = {
  labelValue: "A label and its value, in a tooltip or a copied line: \"deed.pdf: Ready to use…\". Only the punctuation between them is yours (French puts a space before the colon).",
  messages: "What the server refused or couldn't do, by its code. Each is a whole sentence, shown on its own or after a sentence that says what failed (\"The case couldn't be closed. You don't have permission for this.\"). Say what happened and, where there is one, what to do next.",
  messagesBare: "The same code's sentence when the server didn't send the number or reference the full sentence needs.",
  messageAreas: "What is said for a code this screen doesn't know yet, by the part of sūveryn it is about. Whole sentences.",
  messageKinds: "What is said when neither the code nor its part is known: refused, a part is down, something unplanned, or done with a warning. Whole sentences.",
  messageInternalRef: "An unplanned failure. {ref} is the code the administrator finds in the log; keep it at the end, where it is easy to read out.",
  archiveSkipped: "A file inside a .zip that wasn't added. {reason} is the reader's code for why: unsupported (a kind of file sūveryn doesn't read), archive (a .zip inside the .zip), encrypted, too_large, empty, invalid (content doesn't match the extension), damaged. {archive} is the .zip's name.",
  eventMemberAdded: "A row of a case's access log, shown after the person's name (\"Nora Notaris · added a member as reader\"), so it starts with a verb and has no capital or full stop. {role} is the member's role: manager, contributor, or reader.",
  eventRoleChanged: "A row of a case's access log, after the person's name. {role} is the member's new role: manager, contributor, or reader.",
  closeCaseKept: "In the dialog that closes a case. {period} is how long the office keeps a closed case: six_months, one_year, or anything else for five years.",
  calcReadAs: "Under a calculation. {comma} is true when the documents write decimals after a comma, false after a point.",
  runLateDocuments: "A line in a playbook's conversation when documents were added later. {again} is true when the playbook reads its documents again because of them. {documents} are file names, {step} the step's name.",
  pbComputedHow: "How a date was worked out. {before} is true when the term is counted back from the base date. {base} is a date, {term} a term from 'pbTerm' (\"ten days\").",
  pbComputedHowCalendar: "As 'pbComputedHow', with the calendar the days were counted on in brackets (\"Monday to Friday, Belgian public holidays\").",
  pbTerm: "A term inside 'pbComputedHow'. {unit} is day, week, month or year, and anything else a working day; one to twelve are written as words, as deeds do, higher counts as figures.",
  cardCheckWhy: "On a document's card, after reading. {why} is the reader's code for why pages need checking: page_coverage_low (little of the page could be read), layout_failed (the layout wasn't read). {pages} is \"p. 4\" or \"pp. 2 and 7\" from 'pageList'.",
  pbRunningNow: "Under a playbook in the playbook menu, when it is running in this case. {state} says what it is doing: you (waiting for the reader), name (waiting for {name}, a first name), member (waiting for any member of the case), reading (reading the documents), anything else: paused.",
  pbLastRun: "Under a playbook in the playbook menu, when it has run before. {when} is a day (\"Today\"), {state} how it ended, from 'runDone', 'runStopped', 'runCancelled' or 'runFailed'.",
  exportMark: "The line sūveryn writes into a file it makes. {kind} is answer or playbook. Keep \"sūveryn-ref {ref}\" exactly as it is: the server finds its own files by it.",
  exportMarkCase: "As 'exportMark', for a file made in a case; {caseRef} is the case's reference.",
  originWasOutput: "In the Documents overview, under Origin. {kind} is what the uploaded file once was: answer or playbook (a playbook's result).",
  noticedTitle: "The title of the question shown when an uploaded file looks like sūveryn's own output. {kind} is answer or playbook.",
  pageList: "Page numbers in a tight place. {pages} is the numbers, {count} how many there are (\"p. 4\", \"pp. 2 and 7\").",
  backupStep: "Why a backup failed, by the step it failed at. Whole sentences, shown after \"The last backup failed (when).\"",
  clockErrors: "Why the appliance's clock couldn't be set. Whole sentences, shown after \"Not set.\"",
  signInFailed: "A row of an account's sign-in log: why a sign-in failed.",
};
