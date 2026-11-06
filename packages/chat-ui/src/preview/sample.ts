/**
 * The sample office the previews show: fictional people and cases, the same as on the design boards.
 * `answer` is what the stand-in for the gateway (fakeApi.ts) returns for each path.
 */
import type { Account, AccountEvent, Case, CaseEvent, ConversationSummary, Member, UsersList } from "../api";

const DAY = 24 * 60 * 60 * 1000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

export const CASE_124: Case = {
  id: "c124", reference: "124", name: "Van Damme · De Smet", type: "sale", subject: {}, access: "default", state: "open",
  opened_at: ago(40 * DAY), closed_at: null, keep_until: null, keep: false, manager: "u-test", created_by: "u-test",
  updated_at: ago(DAY), my_role: "manager",
};

export const CONVERSATION: ConversationSummary = {
  id: "conv1", title: "Akte van verkoop: nazicht clausules", created_at: ago(2 * DAY), updated_at: ago(DAY), case_id: null,
};

const account = (sub: string, name: string, email: string, admin: boolean, enabled: boolean, last: number | null): Account => ({
  sub, username: email, name, email, admin, enabled, last_sign_in: last === null ? null : ago(last),
});
export const USERS: UsersList = {
  agreement_users: 10,
  users: [
    account("u-test", "Test Beheerder", "test@kantoor.be", true, true, 2 * 60 * 60 * 1000),
    account("u-mieke", "Mieke Delarivière", "mieke@kantoor.be", false, true, 3 * 60 * 60 * 1000),
    account("u-filip", "Filip Tack", "filip@kantoor.be", true, true, DAY),
    account("u-jonas", "Jonas Claes", "jonas.c@kantoor.be", false, true, null),
    account("u-miet", "Miet Vandenberghe", "miet@kantoor.be", false, false, 34 * DAY),
  ],
};

export const ACCOUNT_EVENTS: AccountEvent[] = [
  { at: ago(2 * 60 * 60 * 1000), kind: "signed_in", user: "u-test", name: "Test Beheerder", by: null, reason: null },
  { at: ago(3 * 60 * 60 * 1000), kind: "signed_in", user: "u-mieke", name: "Mieke Delarivière", by: null, reason: null },
  { at: ago(DAY), kind: "added", user: "u-jonas", name: "Jonas Claes", by: "Test Beheerder", reason: null },
];

const member = (user: string, username: string, name: string, role: Member["role"]): Member => ({
  user, username, name, role, added_by: "u-test", added_at: ago(40 * DAY),
});
export const MEMBERS: Member[] = [
  member("u-test", "test@kantoor.be", "Test Beheerder", "manager"),
  member("u-mieke", "mieke@kantoor.be", "Mieke Delarivière", "contributor"),
  member("u-filip", "filip@kantoor.be", "Filip Tack", "contributor"),
];

export const CASE_EVENTS: CaseEvent[] = [
  { id: 4, user: "u-mieke", at: ago(60 * 60 * 1000), action: "uploaded", detail: {} },
  { id: 3, user: "u-mieke", at: ago(65 * 60 * 1000), action: "playbook_started", detail: {} },
  { id: 2, user: "u-filip", at: ago(3 * DAY), action: "access_changed", detail: { access: "restricted" } },
  { id: 1, user: "u-test", at: ago(25 * DAY), action: "created", detail: {} },
];

/** The answers, by method and path (the query left out). Anything else is answered 404. */
export const answer: Record<string, unknown> = {
  "GET /v1/admin/users": USERS,
  "GET /v1/admin/users/events": ACCOUNT_EVENTS,
  "GET /v1/cases/c124/members": MEMBERS,
  "GET /v1/cases/c124/events": CASE_EVENTS,
  "GET /v1/cases/c124/playbooks": [],
  "GET /v1/users": [],
  "GET /v1/admin/backups": null,
};
