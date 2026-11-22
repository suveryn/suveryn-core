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

export default defineConfig({
  gateway: {
    input: { target: input, filters: { tags: groups } },
    output: {
      target: process.env.SUVERYN_GENERATED ?? "src/generated/gateway.ts",
      client: "fetch",
      mode: "single",
      override: { mutator: { path: "src/lib/gateway.ts", name: "gatewayFetch" } },
    },
  },
});
