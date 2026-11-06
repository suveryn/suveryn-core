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

useSampleData();
const params = new URLSearchParams(window.location.search);
const wanted = params.get("lang");
setLang((LANGS as readonly string[]).includes(wanted ?? "") ? (wanted as Lang) : "en", false);
const shown = PREVIEWS.find((p) => p.id === params.get("p"));

function Index() {
  const boards = [...new Set(PREVIEWS.map((p) => p.board))];
  return (
    <main className="preview-index">
      <h1>Screen previews</h1>
      <p>The real screens with sample data, one per state on the design boards. Add <code>&amp;lang=nl</code> or <code>fr</code>.</p>
      {boards.map((b) => (
        <section key={b}>
          <h2>{b}</h2>
          <ul>{PREVIEWS.filter((p) => p.board === b).map((p) => <li key={p.id}><a href={`?p=${p.id}`}>{p.title}</a></li>)}</ul>
        </section>
      ))}
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
