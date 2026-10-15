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
// The component library (src/ui, suveryn-tracker#44) bundles React Aria Components (Apache-2.0) and
// what it depends on, found the same way.
const aria = [];
const walkAria = (name) => {
  // client-only is an empty marker package (no code is bundled from it).
  if (aria.includes(name) || name.startsWith("@types/") || ["react", "react-dom", "client-only"].includes(name)) return;
  aria.push(name);
  Object.keys(JSON.parse(readFileSync(`node_modules/${name}/package.json`, "utf8")).dependencies ?? {}).forEach(walkAria);
};
walkAria("react-aria-components");
// The web setup's QR code (src/ui/QrCode.tsx) is drawn with qrcode-generator, which has no dependencies.
// The charts' axis steps (src/ui/chartScale.ts) come from d3-array (ISC), which brings internmap (ISC).
const bundled = ["react", "react-dom", "scheduler", "lucide-react", ...aria, "qrcode-generator", "d3-array", "internmap",
                 ...office.filter((n) => !aria.includes(n))];
// qrcode-generator ships no licence file: its source header says "Copyright (c) 2009 Kazuhiko Arase,
// licensed under the MIT license", so the MIT text with that notice is written here.
const handWritten = {
  "qrcode-generator": `Copyright (c) 2009 Kazuhiko Arase

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The word "QR Code" is a registered trademark of DENSO WAVE INCORPORATED.`,
};
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
  if (!file && !section && !handWritten[name]) throw new Error(`no licence text for ${name}: add it by hand before shipping`);
  const licence = handWritten[name] ?? (file ? readFileSync(file, "utf8").trim() : section);
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
