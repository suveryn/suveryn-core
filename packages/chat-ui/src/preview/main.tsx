/**
 * Screen previews (src/preview/README.md): /preview.html lists them; /preview.html?p=<id> shows one,
 * &lang=nl or fr for another language. Development only.
 */
import "../styles/fonts.css";
import "../styles/tokens.css";
import "../styles/app.css";
import "./preview.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { LANGS, locale, setLang, type Lang } from "../i18n";
import { I18nProvider } from "../ui";
import { useSampleData } from "./fakeApi";
import { PREVIEWS } from "./previews";
import { stepsRunning } from "./steps";

useSampleData();
const params = new URLSearchParams(window.location.search);
const shown = PREVIEWS.find((p) => p.id === params.get("p"));
const wanted = params.get("lang");
setLang((LANGS as readonly string[]).includes(wanted ?? "") ? (wanted as Lang) : shown?.lang ?? "en", false);
shown?.setup?.();
// A preview without steps is ready once its first data is in (the screenshot script waits for this).
// A preview with steps (steps.tsx) says so itself when its last step is done.
if (shown) setTimeout(() => { if (!stepsRunning()) document.documentElement.setAttribute("data-preview-ready", ""); }, 1500);

/** The setup's screens (setup/SetupApp.tsx, ?screen=): the boards web-00 to web-06 and web-09. */
const SETUP: [string, string][] = [
  ["0", "Welkom (web-00)"], ["1", "1 · Netwerk (web-01)"], ["2", "2 · Beheerder (web-02)"], ["3", "3 · Certificaat (web-03)"],
  ["4", "4 · Ondersteuning (web-04)"], ["5", "5 · Back-ups (web-05)"], ["6#answered", "6 · Nakijken (web-06)"], ["restore", "Terugzetten (web-09)"],
];

/** What the screenshot script photographs (scripts/previews-shoot.mjs): every preview and setup screen, with its width. */
const SHOTS = [
  ...PREVIEWS.map((p) => ({ id: p.id, url: `preview.html?p=${p.id}`, width: p.width ?? 1440 })),
  ...SETUP.map(([screen]) => ({ id: `setup-${screen.replace("#", "-")}`, url: `setup.html?screen=${screen.replace("#", "&v=")}`, width: 1440 })),
];
if (!shown) document.documentElement.setAttribute("data-shots", JSON.stringify(SHOTS));

function Index() {
  const boards = [...new Set(PREVIEWS.map((p) => p.board))];
  return (
    <main className="preview-index">
      <h1>Screen previews</h1>
      <p>The real screens with sample data, one per state on the design boards. Each opens in its board's language; add <code>&amp;lang=en</code>, <code>nl</code> or <code>fr</code> for another.</p>
      {boards.map((b) => (
        <section key={b}>
          <h2>{b}</h2>
          <ul>{PREVIEWS.filter((p) => p.board === b).map((p) => <li key={p.id}><a href={`?p=${p.id}`} onClick={p.width ? (e) => {
            // A phone-width board opens in a window that wide: the screen's own breakpoints then apply.
            e.preventDefault(); window.open(`?p=${p.id}`, p.id, `width=${p.width},height=844`);
          } : undefined}>{p.title}</a></li>)}</ul>
        </section>
      ))}
      <section>
        <h2>S: the appliance's setup</h2>
        <p>The setup's own page with the demo's answers, opened at a step (boards in suveryn-appliance, docs/design/first-boot-setup).</p>
        <ul>{SETUP.map(([screen, title]) => <li key={screen}><a href={`setup.html?screen=${screen}`}>{title}</a></li>)}</ul>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider locale={locale()}>
      {shown ? <div className="preview-stage" data-preview={shown.id}>{shown.render()}</div> : <Index />}
    </I18nProvider>
  </StrictMode>,
);
