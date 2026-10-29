/**
 * A component's body runs on every render, so a call standing in it (a fetch, a setter) runs again with
 * every render it causes: the round 2 check found `departedNames().then(setDeparted)` loose in App's
 * body, about 190 requests a second for each open page. This reads every component's source and fails
 * on a call that stands as a statement of its own in a component's body, outside an effect, a handler
 * or a hook. Hooks (`useX(...)`) are the allowed exception.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
// oxc's parser, as rolldown (Vite's bundler) ships it: TypeScript 7 has no JavaScript API to parse with
import { parseSync } from "rolldown/utils";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const files = [join(SRC, "App.tsx"), ...readdirSync(join(SRC, "components"))
  .filter((f) => f.endsWith(".tsx") && !f.includes(".test.")).map((f) => join(SRC, "components", f))];

type Node = { type: string; start: number; end: number; [k: string]: any };

function looseCalls(path: string, text = readFileSync(path, "utf8")): string[] {
  const { program, errors } = parseSync(path.endsWith(".tsx") ? path : `${path}.tsx`, text);
  expect(errors, path).toEqual([]);
  const found: string[] = [];
  const lineOf = (pos: number) => text.slice(0, pos).split("\n").length;
  const checkBody = (name: string, body: Node | null | undefined) => {
    if (!body || body.type !== "BlockStatement") return;
    for (const st of body.body as Node[]) {
      if (st.type !== "ExpressionStatement") continue;
      let e: Node = st.expression;
      while (e.type === "AwaitExpression" || (e.type === "UnaryExpression" && e.operator === "void")) e = e.argument;
      if (e.type !== "CallExpression") continue;
      // the leftmost callee: departedNames().then(...) is departedNames
      let callee: Node = e;
      while (callee.type === "CallExpression" || callee.type === "MemberExpression") callee = callee.type === "CallExpression" ? callee.callee : callee.object;
      if (callee.type === "Identifier" && /^use[A-Z]/.test(callee.name)) continue;
      found.push(`${path.split("/src/")[1] ?? path}:${lineOf(st.start)} ${name}: ${text.slice(st.start, st.end).slice(0, 80)}`);
    }
  };
  const isComponent = (id: Node | null | undefined) => !!id && id.type === "Identifier" && /^[A-Z]/.test(id.name);
  const visit = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(visit); return; }
    const n = node as Node;
    if (n.type === "FunctionDeclaration" && isComponent(n.id)) checkBody(n.id.name, n.body);
    if (n.type === "VariableDeclarator" && isComponent(n.id) && n.init
        && (n.init.type === "ArrowFunctionExpression" || n.init.type === "FunctionExpression")) checkBody(n.id.name, n.init.body);
    for (const [k, v] of Object.entries(n)) if (k !== "type" && v && typeof v === "object") visit(v);
  };
  visit(program);
  return found;
}

describe("a component's body", () => {
  it("calls nothing outside an effect, a handler or a hook", () => {
    expect(files.length).toBeGreaterThan(10);
    expect(files.flatMap((f) => looseCalls(f))).toEqual([]);
  });

  it("would have caught round 2's loop, and lets hooks and handlers be", () => {
    const text = `export function App() {
  const [d, setDeparted] = useState({});
  useEffect(() => { departedNames().then(setDeparted); }, []);
  const load = () => listMembers("x").then(() => {});
  departedNames().then(setDeparted).catch(() => {});
  return null;
}`;
    expect(looseCalls("App.tsx", text)).toEqual([expect.stringContaining("App: departedNames().then(setDeparted)")]);
  });
});
