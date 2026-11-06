/**
 * Every preview: a real screen or dialog from src/components, given sample data, in one state.
 * `board` is the design board it answers to (canvas "Sūveryn · interface, stand van 6 nov"), so the
 * two can be put side by side. A new screen state gets its preview here in the same change.
 */
import { useEffect, type ReactNode } from "react";
import { AdminView } from "../components/Admin";
import { CloseCaseDialog, DeleteCaseDialog } from "../components/CaseDialogs";
import { AccessLogDialog, MembersDialog } from "../components/CaseMembers";
import { RenameConversationDialog } from "../components/ConversationDialogs";
import { SignOutDialog } from "../components/SignOutDialog";
import { HttpError } from "../api";
import { CASE_124, CONVERSATION } from "./sample";

export type Preview = { id: string; board: string; title: string; render: () => ReactNode };

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

export const PREVIEWS: Preview[] = [
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
