// Writes public/THIRD-PARTY-NOTICES.txt from the licence files of the packages bundled into the UI.
// Lucide (ISC), React (MIT) and the fonts (SIL Open Font Licence) require their notices to travel
// with copies; the file is served next to the UI and included in every build.
import { existsSync, readFileSync, writeFileSync } from "node:fs";

// The Word and Excel downloads (lib/office.ts) bundle docx and write-excel-file with everything they
// depend on: those are listed too, found through their package.json (type definitions aren't bundled).
const office = [];
const walk = (name) => {
  if (office.includes(name) || name.startsWith("@types/") || name === "undici-types") return;
  office.push(name);
  Object.keys(JSON.parse(readFileSync(`node_modules/${name}/package.json`, "utf8")).dependencies ?? {}).forEach(walk);
};
["docx", "write-excel-file"].forEach(walk);
const bundled = ["react", "react-dom", "scheduler", "lucide-react", ...office];
const licenceFile = (name) => ["LICENSE", "LICENSE.md", "LICENSE.markdown", "LICENSE.txt", "LICENCE", "license", "license.md"]
  .map((f) => `node_modules/${name}/${f}`).find(existsSync);
// Fonts come from suveryn-brand (scripts/brand-sync.mjs), each with its OFL.txt.
const fonts = [["Inter", "Inter"], ["Space Grotesk", "SpaceGrotesk"], ["IBM Plex Mono", "IBMPlexMono"]];
const parts = ["Third-party software bundled into the sūveryn chat interface.\n"];
for (const name of bundled) {
  const pkg = JSON.parse(readFileSync(`node_modules/${name}/package.json`, "utf8"));
  const file = licenceFile(name);
  // A few packages (hash.js, isarray) have their licence only in the README's "License" section.
  const readme = existsSync(`node_modules/${name}/README.md`) ? readFileSync(`node_modules/${name}/README.md`, "utf8") : "";
  const section = readme.match(/^#+\s*licen[cs]e\s*$([\s\S]*)/im)?.[1].trim();
  if (!file && !section) throw new Error(`no licence text for ${name}: add it by hand before shipping`);
  const licence = file ? readFileSync(file, "utf8").trim() : section;
  // jszip is dual-licensed (MIT OR GPL-3.0-or-later): the interface uses it under MIT.
  const used = name === "jszip" ? `${pkg.license}, used under MIT` : pkg.license;
  parts.push(`${"=".repeat(72)}\n${name} ${pkg.version} (${used})\n${"=".repeat(72)}\n${licence}\n`);
}
for (const [family, dir] of fonts) {
  const licence = readFileSync(`src/fonts/${dir}/OFL.txt`, "utf8").trim();
  parts.push(`${"=".repeat(72)}\n${family} font (OFL-1.1)\n${"=".repeat(72)}\n${licence}\n`);
}
writeFileSync("public/THIRD-PARTY-NOTICES.txt", parts.join("\n"));
console.log(`THIRD-PARTY-NOTICES.txt: ${bundled.length} packages, ${fonts.length} fonts`);
