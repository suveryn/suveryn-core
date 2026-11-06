/**
 * Every preview: a real screen or dialog from src/components, given sample data, in one state.
 * `board` is the design board it answers to (canvas "Sūveryn · interface, stand van 6 nov"), so the
 * two can be put side by side. A new screen state gets its preview here in the same change.
 */
import { useEffect, type ReactNode } from "react";
import App from "../App";
import { AdminView } from "../components/Admin";
import { CloseCaseDialog, DeleteCaseDialog } from "../components/CaseDialogs";
import { AccessLogDialog, MembersDialog } from "../components/CaseMembers";
import { RenameConversationDialog } from "../components/ConversationDialogs";
import { SignOutDialog } from "../components/SignOutDialog";
import { HttpError } from "../api";
import { CASE_124, CONVERSATION } from "./sample";
import { Steps, type Step } from "./steps";
import { hold, offline, replace } from "./fakeApi";
import { AS_READER, EMPTY_OFFICE, KEY_TEST_DUE, NO_RUN, RUN_DONE, RUN_CANCELLED, RUN_FAILED, RUN_PAUSED, RUN_READING, RUN_STOPPED } from "./sample";
import type { Lang } from "../i18n";

export type Preview = {
  id: string; board: string; title: string; render: () => ReactNode;
  /** The board's language (the dialog boards are English, the rest Dutch); ?lang= overrides it. */
  lang?: Lang;
  /** Changes to the sample office before the screen starts (fakeApi.ts). */
  setup?: () => void;
};

const nothing = () => {};
const never = () => new Promise<void>(() => {});
const fails = () => Promise.reject(new HttpError("the server didn't answer in time", 504));

/** Presses the dialog's main action once it is open: the busy and failed states are reached the
 *  way a person reaches them. */
function PressMain({ children }: { children: ReactNode }) {
  useEffect(() => {
    const t = setTimeout(() => document.querySelector<HTMLElement>('[data-dialog-role="primary"]')?.click(), 50);
    return () => clearTimeout(t);
  }, []);
  return <>{children}</>;
}

/** The whole app, signed in as Mieke Delarivière, brought into a state by `steps`. */
const app = (...steps: Step[]) => () => <Steps steps={steps}><App /></Steps>;

/** Administration on one of its pages, reached as an administrator does: the account menu, Beheer, the page. */
const admin = (page: string, ...steps: Step[]) =>
  app({ click: "Account: Test Beheerder" }, { click: "Beheer" }, ...(page === "Status" ? [] : [{ click: page, within: "Beheer" }]), ...steps);

export const PREVIEWS: Preview[] = [
  // G: the conversation (Dutch, as the boards)
  { id: "g01-start", board: "G01", lang: "nl", title: "Start, persoonlijk", render: app() },
  { id: "g02-case-conversation", board: "G02", lang: "nl", title: "Gesprek in een dossier",
    render: app({ click: "Akte van verkoop: nazicht clausules" }) },
  { id: "g03-collapsed", board: "G03", lang: "nl", title: "Ingeklapte kolom, persoonlijk gesprek",
    render: app({ click: "Wat is een huurkoopformule?" }, { click: "Zijbalk inklappen" }) },
  { id: "g04-account-menu", board: "G04", lang: "nl", title: "Accountmenu",
    render: app({ click: "Account: Test Beheerder" }) },
  { id: "g05-new-menu", board: "G05", lang: "nl", title: "Menu Nieuw",
    render: app({ click: "Nieuw" }) },
  { id: "g06-conversations", board: "G06", lang: "nl", title: "Gesprekken, overzicht", render: app({ click: "Gesprekken" }) },
  { id: "g07-cases", board: "G07", lang: "nl", title: "Dossiers, overzicht", render: app({ click: "Dossiers" }) },
  { id: "g08-documents", board: "G08", lang: "nl", title: "Documenten, overzicht", render: app({ click: "Documenten" }) },
  { id: "g09-offline", board: "G09", lang: "nl", title: "Server niet bereikbaar", setup: () => offline(),
    render: app({ click: "Wat is een huurkoopformule?" }) },
  { id: "g10-busy", board: "G10", lang: "nl", title: "Bezig met een antwoord", setup: () => hold("/v1/chat"),
    render: app({ type: "Wat is een huurkoopformule, in grote lijnen?", into: "Stel een vraag" }, { key: "Enter" }) },
  { id: "g11-source", board: "G11", lang: "nl", title: "Bronpaneel open",
    render: app({ click: "Akte van verkoop: nazicht clausules" }, { click: "Bron 1: Compromis_Schipperskaai.pdf, pagina 7" }) },
  { id: "g12-first-use", board: "G12", lang: "nl", title: "Eerste gebruik", setup: () => replace(EMPTY_OFFICE), render: app() },
  { id: "g14-new-case", board: "G14", lang: "nl", title: "Nieuw dossier",
    render: app({ click: "Nieuw" }, { click: "Nieuw dossier" }) },
  { id: "g16-save-answer", board: "G16", lang: "nl", title: "Antwoord bewaren: Word of Markdown",
    render: app({ click: "Akte van verkoop: nazicht clausules" }, { click: "Andere formaten" }) },
  { id: "g17-ask-about", board: "G17", lang: "nl", title: "Vraag over: documenten kiezen",
    render: app({ click: "123" }, { click: "Vraag over, alle documenten" }) },
  { id: "g18-ask-about-conversation", board: "G18", lang: "nl", title: "Vraag over: antwoord op één gekozen document",
    render: app({ click: "Prijs en kosten" }) },
  { id: "g20-confidential", board: "G20", lang: "nl", title: "Strikt vertrouwelijk dossier",
    render: app({ click: "Dossiers" }, { click: "118" }) },
  { id: "g15-narrow", board: "G15", lang: "nl", title: "Smal scherm (390 px): open op een telefoon", render: app() },
  // P: a playbook in the conversation (Dutch, as the boards): deed intake in case 124, at its checkpoint
  { id: "p01-playbook", board: "P01", lang: "nl", title: "Een playbook in het gesprek", render: app({ click: "Akte-intake" }) },
  { id: "p02-source", board: "P02", lang: "nl", title: "Op een bron geklikt",
    render: app({ click: "Akte-intake" }, { click: "Bron 1: Compromis_DeSmet.pdf, pagina 4" }) },
  { id: "p03-all-facts", board: "P03", lang: "nl", title: "Alle gegevens als naslag",
    render: app({ click: "Akte-intake" }, { click: "Alle 15 gegevens bekijken" }) },
  { id: "p04-start", board: "P04", lang: "nl", title: "1 · Starten vanuit de composer", setup: () => replace(NO_RUN),
    render: app({ click: "124" }, { click: "Een playbook toepassen op dit dossier" }) },
  { id: "p04-steer", board: "P04", lang: "nl", title: "2 · Sturen: het menu van de chip",
    render: app({ click: "Akte-intake" }, { click: "Akte-intake", nth: 1 }) },
  { id: "p04-reading", board: "P04", lang: "nl", title: "3 · Aan het lezen", setup: () => replace(RUN_READING), render: app({ click: "Akte-intake" }) },
  { id: "p04-paused", board: "P04", lang: "nl", title: "4 · Gepauzeerd", setup: () => replace(RUN_PAUSED), render: app({ click: "Akte-intake" }) },
  { id: "p04-stopped", board: "P04", lang: "nl", title: "5 · Gestopt", setup: () => replace(RUN_STOPPED), render: app({ click: "Akte-intake" }) },
  { id: "p04-cancelled", board: "P04", lang: "nl", title: "5 · Geannuleerd", setup: () => replace(RUN_CANCELLED), render: app({ click: "Akte-intake" }) },
  { id: "p04-failed", board: "P04", lang: "nl", title: "6 · Iets misgelopen", setup: () => replace(RUN_FAILED), render: app({ click: "Akte-intake" }) },
  { id: "p04-where", board: "P04", lang: "nl", title: "7 · Waar het staat: Dossiers", render: app({ click: "Dossiers" }) },
  { id: "p04-done", board: "P04", lang: "nl", title: "Klaar: bevestigd, met de samenvatting", setup: () => replace(RUN_DONE), render: app({ click: "Akte-intake" }) },
  { id: "p04-again", board: "P04", lang: "nl", title: "9 · Opnieuw: een nieuwe uitvoering, een nieuw gesprek", setup: () => replace(RUN_DONE),
    render: app({ click: "124" }, { click: "Een playbook toepassen op dit dossier" }) },
  { id: "p04-reader", board: "P04", lang: "nl", title: "8 · Een lezer volgt mee", setup: () => replace(AS_READER), render: app({ click: "Akte-intake" }) },
  // B: administration (Dutch, as the boards)
  { id: "b01-status", board: "B01", lang: "nl", title: "Status", render: admin("Status") },
  { id: "b01-attention", board: "B01", lang: "nl", title: "Status: vraagt aandacht (herstelsleutel niet getest)", setup: () => replace(KEY_TEST_DUE),
    render: admin("Status") },
  { id: "b03-users", board: "B03", lang: "nl", title: "Gebruikers", render: admin("Gebruikers") },
  { id: "b05-cases", board: "B05", lang: "nl", title: "Dossiers", render: admin("Dossiers") },
  { id: "b06-playbooks", board: "B06", lang: "nl", title: "Playbooks", render: admin("Playbooks") },
  { id: "b07-usage", board: "B07", lang: "nl", title: "Verbruik", render: admin("Verbruik") },
  { id: "b08-settings", board: "B08", lang: "nl", title: "Instellingen van het kantoor", render: admin("Instellingen") },
  { id: "b11-backups", board: "B11", lang: "nl", title: "Back-ups", render: admin("Back-ups") },
  // D01: the pattern, the four kinds
  { id: "d01-confirmation", board: "D01", title: "Confirmation: close a case",
    render: () => <CloseCaseDialog open kase={CASE_124} period="5y" onCloseCase={never} onCancel={nothing} /> },
  { id: "d01-choice", board: "D01", title: "Choice: keep your chat history",
    render: () => <SignOutDialog open onKeep={nothing} onDelete={never} onCancel={nothing} /> },
  { id: "d01-form", board: "D01", title: "Form: rename a conversation",
    render: () => <RenameConversationDialog conversation={CONVERSATION} onDone={nothing} onCancel={nothing} /> },
  { id: "d01-information", board: "D01", title: "Information: members of a case (not the manager)",
    render: () => <MembersDialog open kase={{ ...CASE_124, my_role: "contributor" }} canManage={false} canHandOver={false}
                                 officeWide={false} onChanged={nothing} onClose={nothing} /> },
  // D04: risky, busy, failed
  { id: "d04-risky", board: "D04", title: "Risky: delete a case, focus on Cancel",
    render: () => <DeleteCaseDialog open kase={CASE_124} onDelete={never} onCancel={nothing} /> },
  { id: "d04-busy", board: "D04", title: "Busy: deleting",
    render: () => <PressMain><DeleteCaseDialog open kase={CASE_124} onDelete={never} onCancel={nothing} /></PressMain> },
  { id: "d04-failed", board: "D04", title: "Failed: the reason under the text, the buttons back",
    render: () => <PressMain><DeleteCaseDialog open kase={CASE_124} onDelete={fails} onCancel={nothing} /></PressMain> },
  // D06: the manager's view of the members
  { id: "d06-members-manager", board: "D06", title: "Members of a case, as its manager",
    render: () => <MembersDialog open kase={CASE_124} canManage canHandOver officeWide onChanged={nothing} onClose={nothing} /> },
  // D11: tables (the access log is a list today, not a table: see the board)
  { id: "d11-users", board: "D11", title: "Administration › Users: the table",
    render: () => <AdminView me="u-test" onBack={nothing} initialPage="users" onLostAdministration={nothing} /> },
  { id: "d11-access-log", board: "D11", title: "Access log of a case",
    render: () => <AccessLogDialog open kase={CASE_124} onClose={nothing} /> },
];
