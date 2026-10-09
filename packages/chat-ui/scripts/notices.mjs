// Writes public/THIRD-PARTY-NOTICES.txt from the licence files of the packages bundled into the UI.
// Lucide (ISC), React (MIT) and the fonts (SIL Open Font Licence) require their notices to travel
// with copies; the file is served next to the UI and included in every build.
import { readFileSync, writeFileSync } from "node:fs";

const bundled = ["react", "react-dom", "scheduler", "lucide-react",
  "@fontsource/inter", "@fontsource/space-grotesk", "@fontsource/ibm-plex-mono"];
const parts = ["Third-party software bundled into the Sūveryn chat interface.\n"];
for (const name of bundled) {
  const pkg = JSON.parse(readFileSync(`node_modules/${name}/package.json`, "utf8"));
  const licence = readFileSync(`node_modules/${name}/LICENSE`, "utf8").trim();
  parts.push(`${"=".repeat(72)}\n${name} ${pkg.version} (${pkg.license})\n${"=".repeat(72)}\n${licence}\n`);
}
writeFileSync("public/THIRD-PARTY-NOTICES.txt", parts.join("\n"));
console.log(`THIRD-PARTY-NOTICES.txt: ${bundled.length} packages`);
