/**
 * The sample office the previews show: fictional people, cases, documents and conversations, the same as on
 * the design boards. `route` is what the stand-in for the gateway (fakeApi.ts) answers for each request.
 * Nothing here is real data (CLAUDE.md, "Confidential data").
 */
import type {
  Account, AccountEvent, Case, CaseEvent, CaseOverview, ConversationSummary, Health, Me, Member, ModelInfo, PlaybookInfo, PlaybookStep,
  Job, Run, RunFact, RunSummary, SavedConversation, StoredDocument, UsersList,
} from "../api";

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

// ---------- who is signed in ----------
export const ME: Me = { username: "test@kantoor.be", name: "Test Beheerder", sub: "u-test", admin: true, office_wide: true,
                        cases_keep: "5y", avatar: null, account_url: null,
                        office_name: "Thirdexpert Notarissen", admin_console_url: "https://kantoor.local/idp/admin/suveryn/console/" };

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
  kase("c097", "097", "Erfenis Vermeulen", "estate", "reader", { state: "closed", closed_at: ago(5 * 365 * DAY), keep_until: ago(-4 * DAY) }),
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
  uploaded_by: "mieke@kantoor.be", source: true, original: true, ...extra,
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
  conv("conv-erf", "Erfdienstbaarheden", 4 * HOUR, { case_id: "c123" }),
  conv("conv-termijnen", "Betalingen en termijnen", 90 * MIN, { case_id: "c123" }),
  CONVERSATION,
  conv("conv-vergadering", "Samenvatting vergadering met de kopers", DAY, { case_id: "c123", owner: "u-mieke", owner_name: "Mieke", shared: true }),
  conv("conv-vertaling", "Vertaling clausule naar het Frans", 3 * HOUR, { case_id: "c124" }),
  conv("conv-run", "Akte-intake", 63 * MIN, { case_id: "c124", owner: "u-mieke", owner_name: "Mieke", shared: true, run_id: "run-124" }),
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
export const CASE_SETTINGS = { default_access: "office", keep: "5y", conversations_keep: "1y", two_step: false, office_name: "Thirdexpert Notarissen", updated_at: ago(10 * DAY), updated_by: "Test Beheerder" };
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


// ---------- a playbook run (boards P01 to P04): deed intake 1.4 in case 124 ----------
/** As the gateway gives the playbook (packages/playbooks, be_notary/deed-intake.yaml and text/*.json). */
const DEED_LABELS = {
  sellers: "Verkoper(s)", "sellers.name": "Naam", "sellers.address": "Adres", "sellers.register": "Rijksregister- of ondernemingsnummer",
  buyers: "Koper(s)", "buyers.name": "Naam", "buyers.address": "Adres", "buyers.register": "Rijksregister- of ondernemingsnummer",
  property: "Goed", cadastral: "Kadastrale gegevens", price: "Prijs", deposit: "Voorschot of waarborg", agreement_date: "Compromis getekend op",
  deed_deadline: "Akte te verlijden tegen", conditions: "Opschortende voorwaarden", "conditions.condition": "Voorwaarde",
  "conditions.term": "Te vervullen tegen", title: "Eigendomstitel", epc: "Energieprestatiecertificaat", soil: "Bodemattest",
  occupancy: "Bewoning bij levering",
};
const DEED_FACTS = ["sellers", "buyers", "property", "cadastral", "price", "deposit", "agreement_date", "deed_deadline", "conditions",
                    "title", "epc", "soil", "occupancy"];
const step = (id: string, kind: PlaybookStep["kind"], needs: string[] = [], facts: string[] = []): PlaybookStep => ({ id, kind, needs, facts });
export const DEED_INTAKE: PlaybookInfo = {
  id: "playbook/be-notary/deed-intake", slug: "deed-intake", pack: "pack/be-notary", version: "1.4", name: "Deed intake", covered: true,
  facts: DEED_FACTS, case_types: ["sale"], active: true,
  lists: { sellers: ["name", "address", "register"], buyers: ["name", "address", "register"], conditions: ["condition", "term"] },
  kinds: { price: "amount", deposit: "amount", agreement_date: "date", deed_deadline: "date", "conditions.term": "date" },
  steps: [step("agreement", "request"), step("read", "read", ["agreement"], DEED_FACTS), step("missing", "ask", ["read"], DEED_FACTS),
          step("deposit_within_price", "check", ["missing"]), step("deed_after_agreement", "check", ["missing"]),
          step("confirm", "checkpoint", ["missing"]), step("summary", "produce", ["confirm"])],
  text: { nl: { title: "Akte-intake", summary: "Leest de feiten voor de akte uit de documenten", facts_title: "Gegevens voor de akte", labels: DEED_LABELS,
                questions: { agreement: "Laad de ondertekende verkoopovereenkomst op en wat de partijen bezorgden (de vorige akte, de attesten). Ga daarna verder.",
                             missing: "De documenten vermelden {label} niet. Wat is het? Laat leeg als u het nog niet weet." },
                checks: { deposit_within_price: "Het voorschot of de waarborg ligt binnen de prijs",
                          deed_after_agreement: "De uiterste datum van de akte valt na de ondertekening van het compromis" } } },
};
const cite = (n: number, document_id: string, filename: string, page: number, text: string) => ({ n, document_id, filename, page, location: null, text });
const COMPROMIS = (page: number, text: string) => cite(1, "d-compromis-124", "Compromis_DeSmet.pdf", page, text);
const TITEL = (page: number, text: string) => cite(2, "d-titel-124", "Eigendomstitel_1998.pdf", page, text);
const fact = (id: string, value: string, citations: RunFact["citations"], extra: Partial<RunFact> = {}): RunFact => ({
  id, value, citations, issues: [], found: !!value, confirmed: null, source: value ? "document" : "none", ...extra,
});
const RUN_START = ago(70 * MIN);
export const RUN_SUMMARY: RunSummary = {
  id: "run-124", case_id: "c124", playbook_id: DEED_INTAKE.id, playbook_version: "1.4", status: "waiting", step_kind: "checkpoint", documents: ["d-compromis-124", "d-titel-124", "d-bodem-124"],
  started_by: "mieke@kantoor.be", started_at: RUN_START, finished_at: null, confirmed_by: null, confirmed_at: null, model: "Qwen3.8-27B", error: null,
  result_document_id: null, out_of_date: false, step: "confirm", language: "nl", paused_by: null, paused_at: null, ended_by: null, ended_reason: null,
  starter: "u-mieke", conversation_id: "conv-run", title: { nl: "Akte-intake", en: "Deed intake", fr: "Intake de l'acte" },
};
export const RUN: Run = {
  ...RUN_SUMMARY, instruction_like_sources: [], steps: {}, playbook: DEED_INTAKE,
  checks: { deposit_within_price: { status: "holds", rule: "deposit <= price", left: "€ 38.500", right: "€ 385.000", missing: [] },
            deed_after_agreement: { status: "holds", rule: "agreement_date < deed_deadline", left: "12 oktober 2026", right: "12 februari 2027", missing: [] } },
  facts: [
    fact("sellers[1].name", "Jan Van Damme", [COMPROMIS(1, "Verkopers: de heer Jan Van Damme en mevrouw Els Peeters.")]),
    fact("sellers[1].address", "Kerkstraat 14, 9000 Gent", [COMPROMIS(1, "Verkopers: de heer Jan Van Damme en mevrouw Els Peeters, samenwonend te 9000 Gent, Kerkstraat 14.")]),
    fact("sellers[2].name", "Els Peeters", [COMPROMIS(1, "Verkopers: de heer Jan Van Damme en mevrouw Els Peeters.")]),
    fact("buyers[1].name", "Pieter De Smet", [COMPROMIS(1, "Kopers: de heer Pieter De Smet en mevrouw An Claes.")]),
    fact("buyers[2].name", "An Claes", [COMPROMIS(1, "Kopers: de heer Pieter De Smet en mevrouw An Claes.")]),
    fact("property", "Woning, Kerkstraat 14, 9000 Gent", [COMPROMIS(1, "Een woning gelegen te 9000 Gent, Kerkstraat 14.")]),
    fact("cadastral", "Gent, 3e afdeling, sectie B, nr. 412B", [TITEL(1, "Gekend ten kadaster Gent, 3e afdeling, sectie B, nummer 412B.")]),
    fact("price", "€ 385.000", [COMPROMIS(2, "De verkoop wordt toegestaan en aanvaard voor de prijs van driehonderdvijfentachtigduizend euro (€ 385.000).")]),
    fact("deposit", "€ 38.500, op de derdenrekening van notaris Claes", [COMPROMIS(2, "Een voorschot van € 38.500 wordt betaald op de derdenrekening van notaris Claes.")]),
    fact("agreement_date", "12 oktober 2026", [COMPROMIS(9, "Opgemaakt te Gent op 12 oktober 2026.")]),
    fact("deed_deadline", "12 februari 2027", [COMPROMIS(4, "De akte zal verleden worden uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst, en in elk geval na de vervulling van de opschortende voorwaarde.")],
         { needs: "computed", computed: { written: "uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst", from: "agreement_date",
                                          base: "2026-10-12", date: "2027-02-12", amount: 4, unit: "month", direction: "after" } }),
    fact("conditions[1].condition", "Hypothecair krediet, binnen vier weken na ondertekening", [COMPROMIS(5, "Onder de opschortende voorwaarde van het verkrijgen van een hypothecair krediet binnen vier weken na ondertekening.")]),
    fact("title", "Akte van 3 maart 1998, notaris Verhaeghe", [TITEL(3, "Verleden voor notaris Verhaeghe op 3 maart 1998.")]),
    fact("epc", "20260915-0002, label C", [], { source: "person", by: "mieke@kantoor.be", at: ago(64 * MIN), found: false }),
    fact("soil", "", [], { found: false }),
    fact("occupancy", "Vrij bij levering", [COMPROMIS(6, "Het goed wordt vrij van bewoning geleverd.")]),
  ],
  turns: [
    { seq: 1, role: "playbook", step_id: "agreement", by: DEED_INTAKE.id, at: RUN_START, text: "", meta: {} },
    { seq: 2, role: "user", step_id: "agreement", by: "mieke@kantoor.be", at: ago(69 * MIN), text: "Hier zijn ze.",
      meta: { attachments: [{ documentId: "d-compromis-124", filename: "Compromis_DeSmet.pdf" }, { documentId: "d-titel-124", filename: "Eigendomstitel_1998.pdf" },
                            { documentId: "d-bodem-124", filename: "Bodemattest_scan.pdf" }] } },
    { seq: 3, role: "playbook", step_id: "missing", by: DEED_INTAKE.id, at: ago(68 * MIN), text: "", meta: { kind: "ask", facts: ["epc", "soil"], found: 11, total: 13 } },
    { seq: 4, role: "user", step_id: "missing", by: "mieke@kantoor.be", at: ago(64 * MIN), text: "EPC 20260915-0002, label C. Het bodemattest volgt nog.", meta: {} },
    { seq: 5, role: "playbook", step_id: "confirm", by: DEED_INTAKE.id, at: ago(63 * MIN), text: "", meta: { kind: "checkpoint", found: 12, total: 13, issues: 1 } },
  ],
};
export const CASE_124_DOCUMENTS: StoredDocument[] = [
  doc("d-compromis-124", "Compromis_DeSmet.pdf", 12, 70 * MIN),
  doc("d-titel-124", "Eigendomstitel_1998.pdf", 4, 70 * MIN),
  doc("d-bodem-124", "Bodemattest_scan.pdf", 2, 70 * MIN, { status: "needs_review", ocr_pages: 2 }),
];

// ---------- the routes ----------
type Answer = unknown | ((m: RegExpMatchArray, body: unknown) => unknown);
// ---------- uploads (board G13): what the server answers for each file, by name ----------
const job = (id: string, filename: string, more: Partial<Job>): Job => ({ id, filename, status: "ready", document_id: null, ...more });
export const UPLOADS: Record<string, Job> = {
  "Compromis_DeSmet.pdf": job("job-1", "Compromis_DeSmet.pdf", { status: "processing", progress: { step: "read", done: 3, total: 12 }, pages: 12 }),
  "Eigendomstitel_1998.pdf": job("job-2", "Eigendomstitel_1998.pdf", { document_id: "d-up-titel", pages: 9 }),
  "Bodemattest_scan.pdf": job("job-3", "Bodemattest_scan.pdf", { status: "needs_review", document_id: "d-up-bodem", pages: 3,
    warnings: [{ page: 2, kind: "page_coverage_low", detail: "" }] }),
  "Volmacht_koper.pdf": job("job-4", "Volmacht_koper.pdf", { status: "failed", error_code: "password" }),
  "Termijnen_aangepast.docx": job("job-5", "Termijnen_aangepast.docx", { document_id: "d-up-termijnen", pages: 2,
    noticed: { ref: "A-7c21e04d", kind: "answer", line: "Gemaakt door sūveryn: antwoord uit dossier 124, 17-10-2026" } }),
};

/** [method, path pattern (the query is part of the path), answer]. The first match answers. */
export type Route = [string, RegExp, Answer];
export const routes: Route[] = [
  ["GET", /^\/v1\/documents\/jobs\/([^/?]+)/, ([, id]: RegExpMatchArray) => Object.values(UPLOADS).find((j) => j.id === id)],
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
  ["GET", /^\/v1\/cases\/c124\/playbooks\/runs\/run-124$/, () => RUN],
  ["GET", /^\/v1\/cases\/c124\/playbooks$/, [DEED_INTAKE]],
  ["GET", /^\/v1\/cases\/[^/]+\/playbooks$/, []],
  ["GET", /^\/v1\/playbooks\/runs\/active$/, { c124: RUN_SUMMARY }],
  ["GET", /^\/v1\/documents\?case=c124/, { documents: CASE_124_DOCUMENTS, jobs: [] }],
  ["GET", /^\/v1\/conversations\?all=true$/, ALL_CONVERSATIONS],
  ["GET", /^\/v1\/conversations\?case=([^&]+)/, (m: RegExpMatchArray) => CASE_CONVERSATIONS.filter((c) => c.case_id === m[1])],
  ["GET", /^\/v1\/conversations$/, PERSONAL_CONVERSATIONS],
  ["GET", /^\/v1\/conversations\/conv-clauses$/, SAVED],
  ["GET", /^\/v1\/conversations\/conv-huurkoop$/, SAVED_PERSONAL],
  ["GET", /^\/v1\/conversations\/conv-prijs$/, () => SAVED_ABOUT],
  ["GET", /^\/v1\/conversations\/conv-erf$/, () => SAVED_MIXED],
  ["GET", /^\/v1\/conversations\/conv-termijnen$/, () => SAVED_TABLE],
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

/** The run in another state (board P04): the run itself, the case's live runs and the case's playbooks answer accordingly. */
export function runIn(change: Partial<Run>): Route[] {
  const run = { ...RUN, ...change };
  const live = ["reading", "waiting", "paused"].includes(run.status);
  return [
    ["GET", /^\/v1\/cases\/c124\/playbooks\/runs\/run-124$/, run],
    ["GET", /^\/v1\/playbooks\/runs\/active$/, live ? { c124: { ...RUN_SUMMARY, ...change } } : {}],
  ];
}
const later = (min: number) => ago((63 - min) * MIN);
const event = (seq: number, kind: string, by: string, min: number, meta: Record<string, unknown> = {}): Run["turns"][number] =>
  ({ seq, role: "playbook", step_id: "confirm", by, at: later(min), text: "", meta: { kind, ...meta } });
export const RUN_READING = runIn({ status: "reading", step: "read", turns: RUN.turns.slice(0, 2), facts: [], checks: {} });
export const RUN_PAUSED = runIn({ status: "paused", paused_by: "filip@kantoor.be", paused_at: later(15),
                                   turns: [...RUN.turns, event(6, "paused", "filip@kantoor.be", 15)] });
export const RUN_STOPPED = runIn({ status: "stopped", ended_by: "filip@kantoor.be", finished_at: later(20),
                                    turns: [...RUN.turns, event(6, "stopped", "filip@kantoor.be", 20)] });
export const RUN_CANCELLED = runIn({ status: "cancelled", ended_by: "filip@kantoor.be", finished_at: later(20), ended_reason: "verkeerde compromis",
                                      turns: [...RUN.turns, event(6, "cancelled", "filip@kantoor.be", 20, { reason: "verkeerde compromis" })] });
export const RUN_FAILED = runIn({ status: "failed", step: "read", error: "model_unavailable", turns: RUN.turns.slice(0, 2), facts: [], checks: {} });
/** No run in the case yet: starting one (board P04, 1). */
export const NO_RUN: Route[] = [["GET", /^\/v1\/playbooks\/runs\/active$/, {}],
                                ["GET", /^\/v1\/conversations\?case=c124/, CASE_CONVERSATIONS.filter((c) => c.case_id === "c124" && !c.run_id)]];
/** Case 124 as a reader (board P04, 8): follows along, doesn't answer. */
export const AS_READER: Route[] = [["GET", /^\/v1\/cases\/c124$/, { ...CASE_124, my_role: "reader", manager: "u-mieke" }]];

/** Asked about one chosen document (board G18): "Vraag over" under the question, "Op basis van" above the answer. */
const SAVED_ABOUT: SavedConversation = {
  ...CASE_CONVERSATIONS[0],
  turns: [
    { id: "a1", role: "user", text: "Wat is de verkoopprijs, en wanneer moet die betaald worden?", attachments: [],
      about: [{ documentId: "d-compromis", filename: "Compromis_Schipperskaai.pdf" }] },
    { id: "a2", role: "assistant", status: "done", grounded: true, model: "Qwen3.8-27B",
      text: "De prijs bedraagt € 385.000, te betalen bij het verlijden van de akte [1]. Het voorschot van € 38.500 is betaald bij de ondertekening van het compromis [2].",
      citations: [
        { text: "De verkoop wordt toegestaan en aanvaard voor de prijs van € 385.000, te betalen bij het verlijden van de authentieke akte.",
          source: { document_id: "d-compromis", page: 2, location: null } },
        { text: "Een voorschot van € 38.500 werd betaald bij de ondertekening van deze overeenkomst.",
          source: { document_id: "d-compromis", page: 3, location: null } },
      ] },
  ],
};

/** Nothing chosen, the answer from three documents (board G19, 4): "Op basis van 3 documenten" names them. */
const SAVED_MIXED: SavedConversation = {
  ...conv("conv-erf", "Erfdienstbaarheden", 4 * HOUR, { case_id: "c123" }),
  turns: [
    { id: "e1", role: "user", text: "Welke erfdienstbaarheden rusten op het goed?", attachments: [] },
    { id: "e2", role: "assistant", status: "done", grounded: true, model: "Qwen3.8-27B",
      text: "Op het goed rust een erfdienstbaarheid van doorgang over een strook van drie meter langs de oostelijke grens [1]. Het kadaster vermeldt daarnaast een recht van overgang voor nutsleidingen [2]. Het bodemattest noemt geen beperkingen [3].",
      citations: [
        { text: "Het goed is bezwaard met een erfdienstbaarheid van doorgang over een strook van drie meter langs de oostelijke perceelsgrens.",
          source: { document_id: "d-compromis", page: 4, location: null } },
        { text: "Recht van overgang voor nutsleidingen ten voordele van het openbaar net.", source: { document_id: "d-kadaster", page: 1, location: null } },
        { text: "Voor deze grond zijn geen gegevens over bodemverontreiniging beschikbaar.", source: { document_id: "d-bodem", page: 1, location: null } },
      ] },
  ],
};
/** Case 123 as a reader (board G19, 6): sees what each question read, asks nothing. */
export const AS_READER_123: Route[] = [["GET", /^\/v1\/cases\/c123$/, { ...CASE_123, my_role: "reader" }]];

/** The recovery key last tested four months ago (board B01): Status asks for attention. */
export const KEY_TEST_DUE: Route[] = [["GET", /^\/v1\/admin\/backups$/, { ...BACKUPS, key_test: { at: ago(120 * DAY), ok: true } }]];
/** The run finished and confirmed (board P04, 9): a new run starts a new conversation. */
export const RUN_DONE = runIn({ status: "done", step: null, finished_at: ago(30 * MIN), confirmed_by: "mieke@kantoor.be", confirmed_at: ago(30 * MIN),
  turns: [...RUN.turns, { seq: 6, role: "playbook", step_id: "confirm", by: "mieke@kantoor.be", at: ago(30 * MIN), text: "", meta: { kind: "confirmed" } }],
  facts: RUN.facts.map((f) => ({ ...f, confirmed: f.value })) });

/** An answer with a table, saved to its case as a Word document (board G16). */
const SAVED_TABLE: SavedConversation = {
  ...CASE_CONVERSATIONS[1],
  turns: [
    { id: "b1", role: "user", text: "Zet de bedragen en termijnen uit het compromis in een tabel.", attachments: [] },
    { id: "b2", role: "assistant", status: "done", grounded: true, model: "Qwen3.8-27B",
      saved: { documentId: "d-termijnen", filename: "Betalingen en termijnen.docx" },
      text: "Het compromis noemt vier bedragen met hun termijn.\n\n"
        + "| Wat | Bedrag | Termijn | Bron |\n|---|---:|---|---|\n"
        + "| Prijs | € 385.000 | Bij het verlijden van de akte | [1] |\n"
        + "| Voorschot | € 38.500 | Bij ondertekening van het compromis | [2] |\n"
        + "| Saldo | € 346.500 | Bij het verlijden van de akte | [1] |\n"
        + "| Kosten en erelonen | volgens barema | Ten laste van de koper | [3] |",
      citations: [
        { text: "De prijs is betaalbaar bij het verlijden van de authentieke akte.", source: { document_id: "d-compromis", page: 3, location: null } },
        { text: "Een voorschot van € 38.500 werd betaald bij de ondertekening.", source: { document_id: "d-compromis", page: 7, location: null } },
        { text: "Alle kosten, rechten en erelonen van de akte zijn ten laste van de koper.", source: { document_id: "d-compromis", page: 9, location: null } },
      ] },
  ],
};
