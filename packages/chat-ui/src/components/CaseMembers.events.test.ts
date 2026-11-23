/** Every line of a case's access log is worded in every language (suveryn-tracker#250): each action the gateway's
 *  description names (`CaseEvent.action`, held to the gateway's code by its own test) has its own sentence here, never
 *  the action's name as the server says it. */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { CaseEvent } from "../api";
import { TABLES_FOR_TESTS } from "../i18n";
import { eventParts } from "./CaseMembers";

const described = JSON.parse(readFileSync(new URL("../../../api-gateway/openapi.json", import.meta.url), "utf8"));
const ACTIONS: CaseEvent["action"][] = described.components.schemas.CaseEvent.properties.action.enum;

describe("the access log", () => {
  it("has a sentence for every action, in every language", () => {
    expect(ACTIONS.length).toBeGreaterThan(25);
    for (const [lang, m] of Object.entries(TABLES_FOR_TESTS)) {
      for (const action of ACTIONS) {
        const line = { id: 1, user: "u-ines", at: "2026-11-23T09:00:00Z", action, detail: {}, name: "Ines" } satisfies CaseEvent;
        const said = eventParts(line, m as Parameters<typeof eventParts>[1], "Ines");
        expect(said, `${lang} ${action}`).not.toEqual(["Ines", ` ${action}`]);  // what an action without words of its own shows
      }
    }
  });
});
