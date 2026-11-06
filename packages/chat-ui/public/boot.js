/*
 * The page's safety net (the e2e white page of 6 November 2026). A plain script, loaded before the app's
 * own modules and with nothing of its own to fetch, so it runs even when they don't.
 *
 * When one of the app's files fails to load (the browser cancels it because the network changed: a
 * laptop switching Wi-Fi, a VPN connecting; ERR_NETWORK_CHANGED), the app can't start and the page
 * stays white. This reloads the page once. If it fails again within a minute, it shows a card with the
 * mark, what happened and a Reload button (Claude Design's handover of 6 November 2026, boards L01 to
 * L04, Claude outputs/design-handover-load-failure.md).
 *
 * It assumes nothing else arrived: no stylesheet (every style is set here, through the DOM), no font
 * (the brand fonts first, the system's after them), no image (the mark is drawn here). Within the
 * Content-Security-Policy (docs/content-security-policy.md): a file of its own, no markup written as
 * text, styles through the CSSOM. Its few words are here because the app's translations may be the very
 * file that failed. Values are the brand's tokens (v3.7), named beside them.
 */
(function () {
  "use strict";
  var KEY = "suveryn.boot-retry";   // when this tab last reloaded for a failed file (sessionStorage)
  var WINDOW_MS = 60000;
  var failed = false;

  var WORDS = {
    en: { title: "Sūveryn didn't load completely.", text: "The connection may have changed while the page opened.",
          reload: "Reload", help: "Does this keep happening? Ask whoever manages sūveryn at your office." },
    nl: { title: "Sūveryn is niet volledig geladen.", text: "Mogelijk veranderde de verbinding terwijl de pagina opende.",
          reload: "Opnieuw laden", help: "Blijft dit gebeuren? Vraag het aan wie sūveryn op uw kantoor beheert." },
    fr: { title: "Sūveryn ne s'est pas chargé entièrement.", text: "La connexion a peut-être changé pendant l'ouverture de la page.",
          reload: "Recharger", help: "Cela se reproduit ? Demandez à la personne qui gère sūveryn dans votre bureau." }
  };

  var BODY_FONT = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  var TITLE_FONT = '"Space Grotesk", ' + BODY_FONT.slice("Inter, ".length);
  var TEXT = "oklch(0.09 0.014 258)";             // text
  var ACCENT = "oklch(0.677 0.201 34.6)";         // accent
  var ACCENT_HOVER = "oklch(0.617 0.201 34.6)";   // accent-hover
  var FOCUS_RING = "0 0 0 2px oklch(1 0 258), 0 0 0 3px oklch(0.64 0.11 188.4), 0 0 0 6px oklch(0.79 0.125 188.4 / 0.15)";
                                                  // a 2 px gap in bg, the focus line, the glow (on an orange fill)

  function language() {
    var saved = null;
    try { saved = localStorage.getItem("suveryn.lang"); } catch (e) { /* storage blocked */ }
    var langs = [saved].concat(navigator.languages || [navigator.language]);
    for (var i = 0; i < langs.length; i++) {
      var code = String(langs[i] || "").slice(0, 2).toLowerCase();
      if (WORDS[code]) return code;
    }
    return "en";
  }

  function retriedRecently() {
    try { return Date.now() - Number(sessionStorage.getItem(KEY) || 0) < WINDOW_MS; } catch (e) { return true; }
  }

  function el(tag, css, text) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text) node.textContent = text;
    return node;
  }

  /** The mark: three shapes in accent, drawn with presentation attributes (no style). */
  function mark() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", "28");
    svg.setAttribute("height", "28");
    svg.setAttribute("viewBox", "0 0 22 22");
    svg.setAttribute("aria-hidden", "true");
    svg.style.display = "block";
    var shapes = [
      { x: 1, y: 1, width: 20, height: 20, rx: 5, fill: "none", stroke: ACCENT, "stroke-width": 1.6 },
      { x: 6.5, y: 5.5, width: 9, height: 1.8, rx: 0.9, fill: ACCENT },
      { x: 8, y: 9.8, width: 6, height: 6.7, rx: 1.2, fill: "none", stroke: ACCENT, "stroke-width": 1.4 }
    ];
    for (var i = 0; i < shapes.length; i++) {
      var rect = document.createElementNS(ns, "rect");
      for (var name in shapes[i]) rect.setAttribute(name, String(shapes[i][name]));
      svg.appendChild(rect);
    }
    return svg;
  }

  function explain() {
    if (document.getElementById("suveryn-boot-failed")) return;
    var lang = language();
    var words = WORDS[lang];
    var narrow = window.matchMedia && window.matchMedia("(max-width: 520px)").matches;

    // the window: surface; a centred card, or a sheet from the bottom on a phone
    var box = el("div", "position:fixed;inset:0;z-index:2147483647;display:flex;justify-content:center;box-sizing:border-box;"
      + "background:oklch(0.98 0.002 258);" + (narrow ? "align-items:flex-end;padding:0" : "align-items:center;padding:24px"));
    box.id = "suveryn-boot-failed";

    var card = el("div", "box-sizing:border-box;background:oklch(1 0 258);box-shadow:0 8px 24px oklch(0.09 0.014 258 / 0.12);"
      + "display:flex;flex-direction:column;gap:12px;color:" + TEXT + ";font-family:" + BODY_FONT + ";"
      + (narrow ? "width:100%;padding:24px 20px 28px;border-radius:20px 20px 0 0" : "width:540px;max-width:100%;padding:24px;border-radius:14px"));
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "suveryn-boot-title");
    card.setAttribute("aria-describedby", "suveryn-boot-text");
    card.setAttribute("lang", lang);

    var title = el("h1", "margin:4px 0 0;font-family:" + TITLE_FONT + ";font-size:22px;line-height:1.2;font-weight:600", words.title);
    title.id = "suveryn-boot-title";
    var text = el("p", "margin:0;font-size:13.5px;line-height:1.55;color:oklch(0.09 0.014 258 / 0.62)", words.text);  // body-sm, text-dim
    text.id = "suveryn-boot-text";
    var help = el("p", "margin:0;font-size:13.5px;line-height:1.55;color:oklch(0.09 0.014 258 / 0.55)", words.help);  // text-dimmer

    var row = el("div", "display:flex;justify-content:flex-end;margin-top:12px");
    var button = el("button", "min-height:44px;padding:12px 20px;border:1px solid " + ACCENT + ";border-radius:6px;background:" + ACCENT
      + ";color:" + TEXT + ";font-family:" + BODY_FONT + ";font-size:14.5px;line-height:1.2;font-weight:600;cursor:pointer;outline:none"
      + (narrow ? ";width:100%" : ""), words.reload);
    button.type = "button";
    button.addEventListener("click", function () { location.reload(); });
    button.addEventListener("focus", function () { button.style.boxShadow = FOCUS_RING; });
    button.addEventListener("blur", function () { button.style.boxShadow = "none"; });
    button.addEventListener("mouseenter", function () { button.style.background = ACCENT_HOVER; button.style.borderColor = ACCENT_HOVER; });
    button.addEventListener("mouseleave", function () { button.style.background = ACCENT; button.style.borderColor = ACCENT; });
    row.appendChild(button);

    card.appendChild(mark());
    card.appendChild(title);
    card.appendChild(text);
    card.appendChild(help);
    card.appendChild(row);
    box.appendChild(card);
    (document.body || document.documentElement).appendChild(box);
    button.focus();   // the only thing left to do; no close and no Escape: there is nothing behind it
  }

  // A script, module preload or stylesheet of this page that didn't arrive (resource errors don't bubble).
  window.addEventListener("error", function (event) {
    var target = event.target;
    if (failed || !target || target === window) return;
    var tag = target.tagName;
    if (tag !== "SCRIPT" && !(tag === "LINK" && /preload|stylesheet/.test(target.rel || ""))) return;
    failed = true;
    if (!retriedRecently()) {
      try { sessionStorage.setItem(KEY, String(Date.now())); } catch (e) { /* reload anyway */ }
      location.reload();
      return;
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", explain);
    else explain();
  }, true);

  // Everything arrived: forget the retry, so a later failure in this tab may reload once again.
  window.addEventListener("load", function () {
    if (!failed) { try { sessionStorage.removeItem(KEY); } catch (e) { /* nothing to forget */ } }
  });
})();
