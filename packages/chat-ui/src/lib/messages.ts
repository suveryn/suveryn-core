/**
 * What the server says, worded for the reader (the handbook's decision of 12 November 2026, *Messages are codes*;
 * docs/design/messages.md). The server sends and stores a code with parameters, never a sentence: `{kind, code,
 * params}`, a code of the registry (`suveryn_harness/messages.json`, read here as it is). This module words it from
 * the language tables: the code's own words, else its area's, else its kind's. So a code newer than this screen still
 * gets a sentence in the reader's language, and the server's English `title` and `detail` are never shown.
 *
 * Two screens word codes, each for its own reader: the chat (`src/i18n/<lang>.ts`: every code but the web setup's)
 * and the appliance's web setup (`src/setup/i18n/<lang>.ts`: the `setup` area, suveryn-tracker#141). Both meet the
 * backup service's codes; those are worded once, in `src/i18n/backups/<lang>.ts` (#154). The appliance's console
 * words its own (the `network` and `bundle` areas, #160), in suveryn-appliance.
 */
import registry from "../../../harness/src/suveryn_harness/messages.json";
import { Unreachable } from "./gateway";

export type MessageCode = keyof typeof registry.codes;
export type MessageArea = (typeof registry.areas)[number];
/** The codes only the appliance's web setup says, and the ones the chat can meet: every other. */
export type SetupCode = Extract<MessageCode, `setup.${string}`>;
/** The backup service's codes: Administration › Backups and the web setup (a restore) both meet them. */
export type BackupCode = Extract<MessageCode, `backup.${string}`>;
/** The codes only the appliance's console says (its installer, and its screen after installation): a network
 *  setting it refuses, a bundle on the stick it can't trust. Worded in suveryn-appliance's `installer-text.json`. */
export type ConsoleArea = "network" | "bundle";
export type ConsoleCode = Extract<MessageCode, `${ConsoleArea}.${string}`>;
export type ChatCode = Exclude<MessageCode, SetupCode | ConsoleCode>;
export type ChatArea = Exclude<MessageArea, "setup" | ConsoleArea>;
export type MessageKind = "refused" | "unavailable" | "internal" | "warning";
/** A code's parameters: raw numbers and ids, formatted and named here. */
export type Params = Record<string, string | number | null | undefined>;
/** A code's words: a sentence, or a message that takes the code's parameters by name (i18n/message.ts). */
export type Wording = string | WordingMessage;
type WordingMessage = { (values: Record<string, string | number | boolean>): string; readonly params: readonly string[] };
/** A message as it travels: in a Problem Details answer, inside an answer, or stored. */
export type Message = { kind?: string; code?: string; params?: Params | null };
/** A screen's words for codes, from its language file: each code's own, a code's words when a value it needs
 *  wasn't given, each area's, each kind's, and an unplanned failure's with its reference. All whole sentences. */
export type MessageWords = {
  messages: object; messagesBare: object; messageAreas: object;
  messageKinds: Record<MessageKind, string>; messageInternalRef: WordingMessage;
};

/** The wording with the parameters it asks for, or null when one of them wasn't given: a sentence never shows a gap. */
function worded(w: Wording | undefined, p: Params): string | null {
  if (!w) return null;
  if (typeof w === "string") return w;
  const values: Record<string, string | number> = {};
  for (const name of w.params) {
    const v = p[name];
    if (v === null || v === undefined || v === "") return null;
    values[name] = v;
  }
  return w(values);
}

/** The message in the reader's language: by its code, else its area, else its kind. */
export function messageText(msg: Message, m: MessageWords): string {
  const params = msg.params ?? {};
  const code = msg.code ?? "";
  const own = worded((m.messages as Record<string, Wording>)[code], params) ?? (m.messagesBare as Record<string, string>)[code];
  if (own) return own;
  const kind = (msg.kind ?? "refused") as MessageKind;
  const area = (m.messageAreas as Record<string, string>)[code.split(".")[0]];
  // an area's words say a refusal; a part that is down, or something unplanned, is said by its kind
  if (area && kind === "refused") return area;
  if (kind === "internal") return worded(m.messageInternalRef, params) ?? m.messageKinds.internal;
  return m.messageKinds[kind] ?? m.messageKinds.refused;
}

/** The general code a status stands for, for an answer that isn't the gateway's own (a proxy's 502, a page of HTML):
 *  the registry's `general`, which the server reads too. */
export function generalMessage(status: number): Message {
  const general = registry.general as { statuses: Record<string, MessageCode>; client: MessageCode; server: MessageCode };
  const code = general.statuses[String(status)] ?? (status >= 500 ? general.server : general.client);
  return { kind: registry.codes[code].kind, code, params: {} };
}

/** The message in an answer that isn't the one asked for: the gateway's Problem Details, else the status's general code. */
export function problemOf(status: number, body: unknown): Message {
  const b = body as Message | null;
  return b && typeof b === "object" && typeof b.code === "string" ? { kind: b.kind, code: b.code, params: b.params ?? {} } : generalMessage(status);
}

/** The line above the conversation, and which refreshes the screen makes by itself are failing now (by name). */
export type RefreshLine = { shown: string | null; own: string | null; failing: string[] };

/**
 * The line after the refresh `name` (suveryn-tracker#272). `shown` is what the line says, `own` what a refresh put
 * there. A refresh that failed: the gateway's words, said once (a line already standing stays); one that can't reach
 * the gateway leaves the line to the connection check. A refresh that works again takes the line away once no
 * refresh is failing any more, and only while the line is still the refreshes' own: a failure that goes on keeps
 * the line up, steadily.
 */
export function afterRefresh(line: RefreshLine, name: string, failure: Error | null,
                             words: { refreshFailed: (v: { why: string }) => string }): RefreshLine {
  if (failure instanceof Unreachable) return line;
  if (failure === null) {
    const failing = line.failing.filter((n) => n !== name);
    return failing.length === 0 && line.shown !== null && line.shown === line.own
      ? { shown: null, own: null, failing } : { ...line, failing };
  }
  const failing = line.failing.includes(name) ? line.failing : [...line.failing, name];
  if (line.shown !== null) return { ...line, failing };
  const said = words.refreshFailed({ why: failure.message });
  return { shown: said, own: said, failing };
}
