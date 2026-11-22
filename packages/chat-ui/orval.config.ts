// What `npm run generate` writes into src/generated (README.md, "The gateway's code (generated)").
import { readFileSync } from "node:fs";

import { defineConfig } from "orval";

// The groups whose operations the chat UI calls through generated code (suveryn-tracker#159: one area at a time)
// are the ones the gateway describes strictly: their refusals in the one shape. The list itself is kept in one
// place, STRICT in packages/api-gateway/tests/test_description.py, which holds the description to it.
const input = "../api-gateway/openapi.json";
const described = JSON.parse(readFileSync(input, "utf8")) as { paths: Record<string, Record<string, { tags: string[]; responses: object }>> };
const groups = [...new Set(Object.values(described.paths).flatMap((byMethod) => Object.values(byMethod))
  .filter((operation) => JSON.stringify(operation.responses).includes("#/components/schemas/ProblemDetails"))
  .map((operation) => operation.tags[0]))].sort();

// The answer stream's events stand in the description where OpenAPI 3.2 puts what one event of a stream is
// (`itemSchema`), as FastAPI writes it for its own streams. Orval reads OpenAPI 3.1, which has no such place and
// refuses it: it is handed the same under `schema`, so the events' shapes are generated. The stream itself is read by
// hand (src/api.ts, streamChat): Orval generates no reader for one.
type Content = { schema?: unknown; itemSchema?: unknown };
type Described = { paths: Record<string, Record<string, { responses?: Record<string, { content?: Record<string, Content> }> }>> };
const asThreeOne = <Description extends object>(description: Description): Description => {
  for (const byMethod of Object.values((description as unknown as Described).paths)) {
    for (const operation of Object.values(byMethod)) {
      for (const answer of Object.values(operation.responses ?? {})) {
        for (const content of Object.values(answer.content ?? {})) {
          if ("itemSchema" in content) { content.schema = content.itemSchema; delete content.itemSchema; }
        }
      }
    }
  }
  return description;
};

export default defineConfig({
  gateway: {
    input: { target: input, filters: { tags: groups }, override: { transformer: asThreeOne } },
    output: {
      target: process.env.SUVERYN_GENERATED ?? "src/generated/gateway.ts",
      client: "fetch",
      mode: "single",
      override: { mutator: { path: "src/lib/gateway.ts", name: "gatewayFetch" } },
    },
  },
});
