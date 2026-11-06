/*
 * The page's safety net (suveryn-tracker: the e2e white page of 6 November 2026). A plain script, loaded
 * before the app's own modules and with nothing of its own to fetch, so it runs even when they don't.
 *
 * When one of the app's files fails to load (the browser cancels it because the network changed: a
 * laptop switching Wi-Fi, a VPN connecting; ERR_NETWORK_CHANGED), the app can't start and the page
 * stays white. This reloads the page once. If it fails again within a minute, it says so in a sentence
 * with a Reload button instead of leaving a blank page.
 *
 * Within the Content-Security-Policy (docs/content-security-policy.md): a file of its own, no markup
 * written as text, styles set through the DOM. Its few words are here because the app's translations
 * may be the very file that failed.
 */
(function () {
  "use strict";
  var KEY = "suveryn.boot-retry";   // when this tab last reloaded for a failed file (sessionStorage)
  var WINDOW_MS = 60000;
  var failed = false;

  var WORDS = {
    en: { text: "sūveryn didn't load completely. The connection may have changed while the page opened.", reload: "Reload" },
    nl: { text: "sūveryn is niet volledig geladen. Mogelijk veranderde de verbinding terwijl de pagina opende.", reload: "Opnieuw laden" },
    fr: { text: "sūveryn ne s'est pas chargé entièrement. La connexion a peut-être changé pendant l'ouverture de la page.", reload: "Recharger" }
  };

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

  function explain() {
    if (document.getElementById("suveryn-boot-failed")) return;
    var words = WORDS[language()];
    var box = document.createElement("div");
    box.id = "suveryn-boot-failed";
    box.setAttribute("role", "alert");
    // over the whole window: the app's own layout (a full-height root) may already be on the page
    box.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:24px;background:oklch(1 0 0);font:15px/1.5 Inter,system-ui,sans-serif;color:oklch(0.09 0.014 258);text-align:center";
    var p = document.createElement("p");
    p.style.cssText = "max-width:440px;margin:0";
    p.textContent = words.text;
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = words.reload;
    button.style.cssText = "min-height:44px;padding:12px 20px;border:0;border-radius:8px;background:oklch(0.677 0.201 34.6);color:oklch(0.09 0.014 258);font:600 14.5px Inter,system-ui,sans-serif;cursor:pointer";
    button.addEventListener("click", function () { location.reload(); });
    box.appendChild(p);
    box.appendChild(button);
    (document.body || document.documentElement).appendChild(box);
    button.focus();
  }

  // A script or a module preload of this page that didn't arrive (resource errors don't bubble: capture).
  window.addEventListener("error", function (event) {
    var el = event.target;
    if (failed || !el || el === window) return;
    var tag = el.tagName;
    if (tag !== "SCRIPT" && !(tag === "LINK" && /preload|stylesheet/.test(el.rel || ""))) return;
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
