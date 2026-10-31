// Writes src/ui/allowedIcons.ts: every icon in the installed lucide-react, by its own name (not the
// older names lucide keeps as aliases). Run after updating lucide-react: `npm run icons:sync`.
// icon-allowlist.test.ts fails until the list matches the installed package.
import { writeFileSync } from "node:fs";
import { icons } from "lucide-react";

const names = Object.keys(icons).sort();
const version = (await import("lucide-react/package.json", { with: { type: "json" } })).default.version;
const lines = [];
let line = " ";
for (const name of names) {
  const piece = ` "${name}",`;
  if (line.length + piece.length > 100) {
    lines.push(line);
    line = " ";
  }
  line += piece;
}
lines.push(line);

writeFileSync(
  new URL("../src/ui/allowedIcons.ts", import.meta.url),
  `/**
 * Every icon in lucide-react ${version} (${names.length}), by lucide's own name: the set this product
 * draws its icons from (claude/ui-components.md). Written by \`npm run icons:sync\`; don't edit by
 * hand. icon-allowlist.test.ts fails on a lucide-react import that isn't on this list (an older
 * alias such as AlertCircle, where lucide's name is CircleAlert: one icon, one name everywhere) and
 * when this list no longer matches the installed lucide-react.
 */
export const ALLOWED_ICONS = [
${lines.join("\n")}
] as const;
`,
);
console.log(`allowedIcons.ts: ${names.length} icons from lucide-react ${version}`);
