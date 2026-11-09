#!/usr/bin/env node
/**
 * Photographs every screen preview and setup screen (src/preview/, the README's "Screen previews") and
 * compares each with its baseline in src/preview/baseline/, so a screen that drifts from its design board
 * is seen in the pull request that moves it (the handbook's decision of 6 November 2026).
 *
 *   npm run previews:check     every preview against its baseline; exits 1 and writes .previews/ on a difference
 *   npm run previews:update    takes new baselines (after a change to a screen that its board agrees with)
 *   node scripts/previews-shoot.mjs --only g01-start,b08-settings     a few
 *
 * Needs Playwright's Chromium (npx playwright install chromium). Starts vite itself on a free port. The
 * clock is fixed at 8 November 2026, 11:30 in Brussels, so dates and "vandaag" never change between runs; a step's
 * own timers still run. A difference is a pixel that differs clearly (pixelmatch, threshold 0.1) and more
 * of them than --tolerance (default 0.05 % of the image): anti-aliasing may differ a little between
 * Chromium builds, a moved button never.
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE = join(ROOT, "src", "preview", "baseline");
const OUT = join(ROOT, ".previews");
const FIXED_TIME = new Date("2026-11-08T11:30:00+01:00");
const args = process.argv.slice(2);
const update = args.includes("--update");
const flag = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const only = (flag("--only") ?? "").split(",").filter(Boolean);
const tolerance = Number(flag("--tolerance") ?? 0.05) / 100;

/** Starts vite on a free port and resolves with its origin. */
function startVite() {
  return new Promise((resolve, reject) => {
    // NO_COLOR: on GitHub (CI set) vite colours its lines, and the escape codes would hide the address.
    // vite itself, not through npx: killing npx would leave vite running and the script waiting on its pipes.
    const vite = spawn(process.execPath, [join(ROOT, "node_modules/vite/bin/vite.js"), "--port", "0", "--strictPort"], {
      cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, NO_COLOR: "1", FORCE_COLOR: "0" },
    });
    let out = "";
    vite.stdout.on("data", (d) => {
      out += d.toString().replace(/\x1b\[[0-9;]*m/g, "");
      const m = out.match(/Local:\s+(http:\/\/[^\s/]+)/);
      if (m) resolve({ origin: m[1].replace("localhost", "127.0.0.1"), stop: () => vite.kill() });
    });
    vite.stderr.on("data", (d) => { out += d.toString(); });
    vite.on("exit", (code) => reject(new Error(`vite stopped (${code}):\n${out}`)));
    setTimeout(() => reject(new Error(`vite didn't start:\n${out}`)), 30_000);
  });
}

async function shoot(page, origin, s) {
  const width = s.width, height = width <= 480 ? 844 : 900;
  await page.setViewportSize({ width, height });
  await page.clock.setFixedTime(FIXED_TIME);
  await page.goto(`${origin}/${s.url}`);
  await page.mouse.click(width - 4, height - 4);  // a person's first click: keyboard focus rings stay off
  await page.waitForSelector("html[data-preview-ready]", { timeout: 30_000 });
  await page.waitForTimeout(300);
  return page.screenshot({ animations: "disabled", caret: "hide" });
}

/** Pixels that differ between two PNG buffers, and the diff image; null when sizes differ. */
function compare(a, b) {
  const pa = PNG.sync.read(a), pb = PNG.sync.read(b);
  if (pa.width !== pb.width || pa.height !== pb.height) return { differing: Infinity, total: pa.width * pa.height, diff: null };
  const diff = new PNG({ width: pa.width, height: pa.height });
  const differing = pixelmatch(pa.data, pb.data, diff.data, pa.width, pa.height, { threshold: 0.1 });
  return { differing, total: pa.width * pa.height, diff: PNG.sync.write(diff) };
}

const { origin, stop } = await startVite();
const browser = await chromium.launch();
try {
  // the office's clock and language, wherever the script runs (a CI runner is in UTC)
  const page = await browser.newPage({ timezoneId: "Europe/Brussels", locale: "nl-BE" });
  await page.goto(`${origin}/preview.html`);
  await page.waitForSelector("html[data-shots]");
  const shots = JSON.parse(await page.getAttribute("html", "data-shots")).filter((s) => !only.length || only.includes(s.id));
  mkdirSync(BASELINE, { recursive: true });
  rmSync(OUT, { recursive: true, force: true });
  const changed = [], missing = [], same = [];
  for (const s of shots) {
    const png = await shoot(page, origin, s);
    const file = join(BASELINE, `${s.id}.png`);
    if (update) { writeFileSync(file, png); same.push(s.id); continue; }
    if (!existsSync(file)) { missing.push(s.id); mkdirSync(OUT, { recursive: true }); writeFileSync(join(OUT, `${s.id}.png`), png); continue; }
    const { differing, total, diff } = compare(readFileSync(file), png);
    if (differing / total <= tolerance) { same.push(s.id); continue; }
    changed.push([s.id, differing, total]);
    mkdirSync(join(OUT, "diff"), { recursive: true });
    writeFileSync(join(OUT, `${s.id}.png`), png);
    if (diff) writeFileSync(join(OUT, "diff", `${s.id}.png`), diff);
  }
  if (update) {
    const stale = readdirSync(BASELINE).filter((f) => f.endsWith(".png") && !shots.some((s) => `${s.id}.png` === f) && !only.length);
    for (const f of stale) rmSync(join(BASELINE, f));
    console.log(`${same.length} baselines written to src/preview/baseline/${stale.length ? `, ${stale.length} stale ones removed` : ""}`);
  } else {
    console.log(`${same.length} unchanged`);
    for (const [id, d, t] of changed) console.log(`changed  ${id}: ${d === Infinity ? "another size" : `${((d / t) * 100).toFixed(2)} % of the pixels`} (.previews/${id}.png, .previews/diff/${id}.png)`);
    for (const id of missing) console.log(`missing  ${id}: no baseline (.previews/${id}.png); npm run previews:update takes it`);
    if (changed.length || missing.length) {
      console.log("\nA changed screen is checked against its design board before the baseline moves: npm run previews:update, then commit src/preview/baseline/.");
      process.exitCode = 1;
    }
  }
} finally {
  await browser.close();
  stop();
}
