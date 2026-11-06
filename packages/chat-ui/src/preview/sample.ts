/**
 * The sample office the previews show: fictional people, cases, documents and conversations, the same as on
 * the design boards. `route` is what the stand-in for the gateway (fakeApi.ts) answers for each request.
 * Nothing here is real data (CLAUDE.md, "Confidential data").
 */
import type {
  Account, AccountEvent, Case, CaseEvent, CaseOverview, ConversationSummary, Health, Me, Member, ModelInfo,
  SavedConversation, StoredDocument, UsersList,
} from "../api";

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

// ---------- who is signed in ----------
export const ME: Me = { username: "test@kantoor.be", name: "Test Beheerder", sub: "u-test", admin: true, office_wide: true,
                        cases_keep: "5y", avatar: null, account_url: null };

export const HEALTH: Health = {
  status: "ok",
  backend: { reachable: true, status: "ok", model: "Qwen3.8-27B" },
  documents: { status: "ready", detail: null },
  auth: { status: "ready", detail: null },
  history: { status: "ready", detail: null },
  cases: { status: "ready", detail: null },
  directory: { status: "ready", detail: null },
};
export const MODELS: ModelInfo[] = [{ id: "Qwen3.8-27B", loaded: true, default: true, thinks: true }, { id: "Gemma-4-12B", loaded: false, default: false, thinks: false }];

// ---------- people ----------
const account = (sub: string, name: string, email: string, admin: boolean, enabled: boolean, last: number | null): Account => ({
  sub, username: email, name, email, admin, enabled, last_sign_in: last === null ? null : ago(last),
});
export const USERS: UsersList = {
  agreement_users: 10,
  users: [
    account("u-test", "Test Beheerder", "test@kantoor.be", true, true, 2 * HOUR),
    account("u-mieke", "Mieke Delarivière", "mieke@kantoor.be", true, true, 3 * HOUR),
    account("u-filip", "Filip Tack", "filip@kantoor.be", true, true, DAY),
    account("u-jonas", "Jonas Claes", "jonas.c@kantoor.be", false, true, null),
    account("u-miet", "Miet Vandenberghe", "miet@kantoor.be", false, false, 34 * DAY),
  ],
};
export const ACCOUNT_EVENTS: AccountEvent[] = [
  { at: ago(2 * HOUR), kind: "signed_in", user: "u-test", name: "Test Beheerder", by: null, reason: null },
  { at: ago(3 * HOUR), kind: "signed_in", user: "u-mieke", name: "Mieke Delarivière", by: null, reason: null },
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

// ---------- cases ----------
const kase = (id: string, reference: string, name: string, type: string, my_role: Case["my_role"], extra: Partial<Case> = {}): Case => ({
  id, reference, name, type, subject: {}, access: "default", state: "open", opened_at: ago(40 * DAY), closed_at: null,
  keep_until: null, keep: false, manager: "u-test", created_by: "u-test", updated_at: ago(HOUR), my_role, ...extra,
});
export const CASE_123 = kase("c123", "123", "Thirdexpert Management & Consulting", "sale", "manager", { pinned: true });
export const CASE_124 = kase("c124", "124", "Van Damme · De Smet", "sale", "manager", { pinned: true, updated_at: ago(DAY) });
export const CASES: Case[] = [
  CASE_123,
  CASE_124,
  kase("c121", "121", "Hypotheek Wouters", "sale", "contributor", { updated_at: ago(2 * DAY) }),
  kase("c119", "119", "Oprichting Bakkerij Peeters BV", "company-formation", "contributor", { updated_at: ago(4 * DAY), manager: "u-filip" }),
  kase("c118", "118", "Schenking Claes", "gift", "contributor", { updated_at: ago(6 * DAY), confidential: true, access: "restricted", manager: "u-mieke" }),
  kase("c112", "112", "Verkoop Kluizendorp", "sale", "reader", { updated_at: ago(9 * DAY), manager: "u-filip" }),
  kase("c109", "109", "Huwelijkscontract Janssens · Maes", "marriage-contract", "contributor", { updated_at: ago(12 * DAY) }),
  kase("c097", "097", "Erfenis Vermeulen", "estate", "reader", { state: "closed", closed_at: ago(20 * DAY), keep_until: ago(-5 * 365 * DAY) }),
];
export const CASES_OVERVIEW: CaseOverview[] = CASES.map((c) => ({
  ...c, members: MEMBERS, last_activity_at: c.updated_at, last_activity_by: "Mieke Delarivière",
}));
export const CASE_EVENTS: CaseEvent[] = [
  { id: 4, user: "u-mieke", at: ago(HOUR), action: "uploaded", detail: {} },
  { id: 3, user: "u-mieke", at: ago(65 * MIN), action: "playbook_started", detail: {} },
  { id: 2, user: "u-filip", at: ago(3 * DAY), action: "access_changed", detail: { access: "restricted" } },
  { id: 1, user: "u-test", at: ago(25 * DAY), action: "created", detail: {} },
];

// ---------- documents ----------
const doc = (id: string, filename: string, pages: number, when: number, extra: Partial<StoredDocument> = {}): StoredDocument => ({
  id, filename, pages, ocr_pages: 0, status: "ok", warnings: [], created_at: ago(when), origin: "uploaded",
  uploaded_by: "mieke@kantoor.be", source: true, ...extra,
});
export const CASE_DOCUMENTS: StoredDocument[] = [
  doc("d-compromis", "Compromis_Schipperskaai.pdf", 14, HOUR),
  doc("d-kadaster", "Kadastrale legger Schipperskaai.pdf", 3, 2 * DAY),
  doc("d-bodem", "Bodemattest OVAM.pdf", 2, 2 * DAY),
  doc("d-epc", "EPC-certificaat.pdf", 4, 3 * DAY, { status: "needs_review", ocr_pages: 4 }),
];
export const PERSONAL_DOCUMENTS: StoredDocument[] = [
  doc("d-volmacht", "Volmacht_FR.pdf", 2, 5 * DAY),
];
export const ALL_DOCUMENTS = [
  ...CASE_DOCUMENTS.map((d) => ({ ...d, case_id: "c123" as string | null })),
  ...PERSONAL_DOCUMENTS.map((d) => ({ ...d, case_id: null as string | null })),
];

// ---------- conversations ----------
const conv = (id: string, title: string, when: number, extra: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id, title, created_at: ago(when + HOUR), updated_at: ago(when), case_id: null, owner: "u-test", messages: 2, ...extra,
});
export const CONVERSATION = conv("conv-clauses", "Akte van verkoop: nazicht clausules", 2 * HOUR, { case_id: "c123" });
export const CASE_CONVERSATIONS: ConversationSummary[] = [
  conv("conv-prijs", "Prijs en kosten", HOUR, { case_id: "c123" }),
  CONVERSATION,
  conv("conv-vergadering", "Samenvatting vergadering met de kopers", DAY, { case_id: "c123", owner: "u-mieke", owner_name: "Mieke", shared: true }),
  conv("conv-vertaling", "Vertaling clausule naar het Frans", 3 * HOUR, { case_id: "c124" }),
  conv("conv-hypotheek", "Hypotheekvoorwaarden vergelijken", 2 * DAY, { case_id: "c121", owner: "u-mieke", owner_name: "Mieke", shared: true }),
];
export const PERSONAL_CONVERSATIONS: ConversationSummary[] = [
  conv("conv-brief", "Standaardbrief aan de koper", 5 * HOUR, { pinned: true }),
  conv("conv-huurkoop", "Wat is een huurkoopformule?", DAY),
  conv("conv-onboarding", "Checklist onboarding nieuwe medewerker", 4 * DAY),
];
export const ALL_CONVERSATIONS = [...CASE_CONVERSATIONS, ...PERSONAL_CONVERSATIONS];

/** The open conversation: a question about the case's documents, answered with two sources (board G02). */
export const SAVED: SavedConversation = {
  ...CONVERSATION,
  turns: [
    { id: "t1", role: "user", text: "Welke opschortende voorwaarden staan er in het compromis, en tegen wanneer moet de financiering rond zijn?", attachments: [] },
    {
      id: "t2", role: "assistant", status: "done", grounded: true, model: "Qwen3.8-27B", thinking: true,
      text: "Het compromis bevat één opschortende voorwaarde: het verkrijgen van een hypothecair krediet door de kopers [1]. "
        + "De kopers moeten de toekenning of weigering van het krediet schriftelijk meedelen binnen vier weken na ondertekening, uiterlijk op [DATUM UIT HET DOCUMENT] [2].\n\n"
        + "Een voorwaarde over stedenbouwkundige vergunningen staat niet in het compromis.",
      citations: [
        { text: "De verkoop geschiedt onder de opschortende voorwaarde van het verkrijgen door de kopers van een hypothecair krediet.",
          source: { document_id: "d-compromis", page: 7, location: null } },
        { text: "De kopers delen de toekenning of weigering van het krediet schriftelijk mee binnen vier weken na ondertekening van deze overeenkomst.",
          source: { document_id: "d-compromis", page: 9, location: null } },
      ],
    },
  ],
};

/** A personal conversation without documents (board G03). */
export const SAVED_PERSONAL: SavedConversation = {
  ...PERSONAL_CONVERSATIONS[1],
  turns: [
    { id: "p1", role: "user", text: "Wat is een huurkoopformule, in grote lijnen?", attachments: [] },
    { id: "p2", role: "assistant", status: "done", grounded: false, model: "Qwen3.8-27B", citations: [],
      text: "Bij huurkoop betaalt de koper periodiek een bedrag dat deels als huur en deels als afbetaling op de prijs geldt. De eigendom gaat pas over bij de laatste betaling." },
  ],
};

// ---------- administration ----------
const check = (id: string, extra: Record<string, unknown> = {}) => ({
  id, ok: true, since: null, in_progress: null, waiting: null, free: null, total: null, ...extra,
});
export const ADMIN_STATUS = {
  checked_at: ago(0), version: "2026.11.1",
  checks: [check("answering", { in_progress: 1, waiting: 0 }), check("reading", { in_progress: 0, waiting: 0 }), check("signin"),
           check("data"), check("disk", { free: 1_420_000_000_000, total: 2_000_000_000_000 }), check("clock", { offset_ms: 120, synced: true })],
};
export const ADMIN_CASES = CASES.map((c) => ({ ...c, manager_username: "test@kantoor.be", manager_name: "Test Beheerder", members: 3 }));
export const CASE_SETTINGS = { default_access: "office", keep: "5y", conversations_keep: "1y", two_step: false, updated_at: ago(10 * DAY), updated_by: "Test Beheerder" };
const totals = (requests: number, tokens: number) => ({ requests, prompt_tokens: Math.round(tokens * 0.9), completion_tokens: Math.round(tokens * 0.1), total_tokens: tokens });
export const OFFICE_USAGE = {
  start: ago(30 * DAY), end: ago(0), step: "1 day", totals: totals(777, 4_200_000), by_kind: { chat: totals(600, 2_980_000), summary: totals(120, 760_000), "playbook-step": totals(57, 460_000) },
  series: Array.from({ length: 30 }, (_, i) => ({ start: ago((30 - i) * DAY), ...totals(10 + ((i * 7) % 30), 60_000 + ((i * 37_000) % 200_000)) })),
  per_user: [
    { user_id: "u-mieke", username: "mieke@kantoor.be", name: "Mieke Delarivière", totals: totals(412, 2_200_000), cost: null },
    { user_id: "u-filip", username: "filip@kantoor.be", name: "Filip Tack", totals: totals(268, 1_500_000), cost: null },
    { user_id: "u-test", username: "test@kantoor.be", name: "Test Beheerder", totals: totals(97, 500_000), cost: null },
  ],
  rates: { input_per_million: "0", output_per_million: "0", currency: "EUR" }, cost: "0",
};
export const BACKUPS = {
  available: true, configured: true, target: "usb", retention_days: 30, last_attempt: ago(7 * HOUR),
  last_success: { at: ago(7 * HOUR), size: 1_234_567_890, on_target: 30, oldest: ago(30 * DAY), disk: "Samsung T7" }, last_error: null,
  key_test: { at: ago(12 * DAY), ok: true }, settings: { target: "usb", disk: "Samsung T7", protocol: null, address: null, user: null,
  has_password: false, retention_days: 30, hour: 2, recipient: "test@kantoor.be", next_run: ago(-17 * HOUR) },
};

/** The installed playbooks (board B06): three certified, one of the office's own. */
const playbook = (slug: string, title: string, version: string, pack: string, types: string[], covered: boolean, active: boolean) => ({
  id: `pb-${slug}`, slug, pack, version, name: title, covered, facts: [], case_types: types, active,
  text: { nl: { title, summary: "", labels: {} }, en: { title, summary: "", labels: {} }, fr: { title, summary: "", labels: {} } },
});
export const PLAYBOOKS = [
  playbook("akte-intake", "Akte-intake", "v1.0", "notariaat-be", ["sale"], true, true),
  playbook("oprichting", "Oprichting vennootschap", "v0.9", "notariaat-be", ["company-formation"], true, true),
  playbook("nalatenschap", "Aangifte nalatenschap", "v0.4", "notariaat-be", ["estate"], true, false),
  playbook("kantoor", "[Playbook van het kantoor]", "v0.3", "kantoor", ["estate", "gift"], false, true),
];

// ---------- the routes ----------
type Answer = unknown | ((m: RegExpMatchArray, body: unknown) => unknown);
/** [method, path pattern (the query is part of the path), answer]. The first match answers. */
export type Route = [string, RegExp, Answer];
export const routes: Route[] = [
  ["GET", /^\/auth\/me$/, ME],
  ["GET", /^\/health$/, HEALTH],
  ["GET", /^\/v1\/clock$/, () => ({ now_ms: Date.now() })],
  ["GET", /^\/v1\/models$/, MODELS],
  ["GET", /^\/v1\/cases\?closed=true$/, CASES],
  ["GET", /^\/v1\/cases$/, CASES.filter((c) => c.state === "open")],
  ["GET", /^\/v1\/cases\/overview$/, CASES_OVERVIEW],
  ["GET", /^\/v1\/cases\/([^/?]+)$/, (m: RegExpMatchArray) => CASES.find((c) => c.id === m[1]) ?? CASE_123],
  ["GET", /^\/v1\/cases\/[^/]+\/members$/, MEMBERS],
  ["GET", /^\/v1\/cases\/[^/]+\/events$/, CASE_EVENTS],
  ["GET", /^\/v1\/cases\/[^/]+\/playbooks$/, []],
  ["GET", /^\/v1\/playbooks\/runs\/active$/, {}],
  ["GET", /^\/v1\/conversations\?all=true$/, ALL_CONVERSATIONS],
  ["GET", /^\/v1\/conversations\?case=([^&]+)/, (m: RegExpMatchArray) => CASE_CONVERSATIONS.filter((c) => c.case_id === m[1])],
  ["GET", /^\/v1\/conversations$/, PERSONAL_CONVERSATIONS],
  ["GET", /^\/v1\/conversations\/conv-clauses$/, SAVED],
  ["GET", /^\/v1\/conversations\/conv-huurkoop$/, SAVED_PERSONAL],
  ["GET", /^\/v1\/conversations\/([^/?]+)$/, (m: RegExpMatchArray) => ({ ...(ALL_CONVERSATIONS.find((c) => c.id === m[1]) ?? CONVERSATION), turns: [] })],
  ["GET", /^\/v1\/documents\/all$/, { documents: ALL_DOCUMENTS }],
  ["GET", /^\/v1\/documents\?case=c123/, { documents: CASE_DOCUMENTS, jobs: [] }],
  ["GET", /^\/v1\/documents\?case=/, { documents: [], jobs: [] }],
  ["GET", /^\/v1\/documents$/, { documents: PERSONAL_DOCUMENTS, jobs: [] }],
  ["GET", /^\/v1\/users\/departed$/, {}],
  ["GET", /^\/v1\/users\?/, []],
  ["GET", /^\/v1\/usage\?/, { start: ago(DAY), end: ago(0), step: "1 hour", totals: { requests: 12, prompt_tokens: 48000, completion_tokens: 6000, total_tokens: 54000 }, series: [], by_kind: {} }],
  ["GET", /^\/v1\/admin\/users$/, USERS],
  ["GET", /^\/v1\/admin\/users\/events/, ACCOUNT_EVENTS],
  ["GET", /^\/v1\/admin\/playbooks$/, PLAYBOOKS],
  ["GET", /^\/v1\/admin\/backups$/, BACKUPS],
  ["GET", /^\/v1\/admin\/status$/, ADMIN_STATUS],
  ["GET", /^\/v1\/admin\/cases$/, ADMIN_CASES],
  ["GET", /^\/v1\/admin\/cases\/settings$/, CASE_SETTINGS],
  ["GET", /^\/v1\/admin\/usage\/rates$/, OFFICE_USAGE.rates],
  ["GET", /^\/v1\/admin\/usage\?/, OFFICE_USAGE],
];

/** A new office's first day (board G12): Ellen Peeters, no cases, no conversations, no documents. */
export const EMPTY_OFFICE: Route[] = [
  ["GET", /^\/auth\/me$/, { ...ME, username: "ellen@kantoor.be", name: "Ellen Peeters", sub: "u-ellen", admin: false }],
  ["GET", /^\/v1\/cases(\?closed=true)?$/, []],
  ["GET", /^\/v1\/cases\/overview$/, []],
  ["GET", /^\/v1\/conversations/, []],
  ["GET", /^\/v1\/documents\/all$/, { documents: [] }],
  ["GET", /^\/v1\/documents/, { documents: [], jobs: [] }],
];
