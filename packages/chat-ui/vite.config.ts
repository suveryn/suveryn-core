/// <reference types="vitest/config" />
import optimizeLocales from "@react-aria/optimize-locales-plugin";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

// In development the UI runs on Vite (port 5173) and proxies the API to the gateway.
// SUVERYN_API defaults to a local gateway, e.g. one reached through an SSH tunnel to the GPU box.
const api = process.env.SUVERYN_API ?? "http://127.0.0.1:8000";

/**
 * CSP EXCEPTION 2 of 2 (docs/content-security-policy.md, "The two exceptions we handle today").
 *
 * React Aria writes an inline <style> while a menu or dialog keeps the page from scrolling on iPhone
 * and iPad (usePreventScroll). The appliance's CSP blocks inline styles (style-src 'self'), so this
 * replaces it, at build time, with an attribute on <html> that a rule in src/ui/ui.css matches: the
 * same effect, applied at the same moment, and no violation. The match is exact: if a React Aria
 * update changes that code, the build fails here rather than silently bringing the <style> back.
 * (The other <style> React Aria writes, for pressable elements, it skips by itself: src/ui/csp.ts.)
 *
 * When the build stops with "React Aria's inline <style> … changed": follow "When the build stops
 * after a React Aria update" in docs/content-security-policy.md. Never loosen the CSP instead (no
 * 'unsafe-inline', nonce or hash); the same document says why. Tested in src/setup/setup.test.ts.
 */
export const PREVENT_SCROLL_STYLE = `    let style = document.createElement('style');
    let nonce = (0, $2b2d34ff061957fb$export$2b85b721e524d74b)();
    if (nonce) style.nonce = nonce;
    style.textContent = \`
@layer {
  * {
    overscroll-behavior: contain;
  }
}\`.trim();
    document.head.prepend(style);`;
const PREVENT_SCROLL_ATTRIBUTE = `    // sūveryn (vite.config.ts): an attribute matched by src/ui/ui.css instead of an inline <style> (CSP).
    document.documentElement.setAttribute('data-ui-prevent-scroll', '');
    let style = { remove: ()=>document.documentElement.removeAttribute('data-ui-prevent-scroll') };`;

export function reactAriaCsp(): Plugin {
  return {
    name: "suveryn-react-aria-csp",
    enforce: "pre",
    transform(code, id) {
      if (!/[\\/]react-aria[\\/]dist[\\/]private[\\/]overlays[\\/]usePreventScroll\.m?js$/.test(id.split("?")[0])) return null;
      if (!code.includes(PREVENT_SCROLL_STYLE)) {
        throw new Error(`${id}: React Aria's inline <style> for preventing scroll changed; update reactAriaCsp in vite.config.ts`);
      }
      return { code: code.replace(PREVENT_SCROLL_STYLE, PREVENT_SCROLL_ATTRIBUTE), map: null };
    },
  };
}

/**
 * Development only. Leaving React Aria out of the optimiser (above) means the browser gets its
 * CommonJS dependency use-sync-external-store/shim as-is, and stops at "does not provide an export
 * named 'useSyncExternalStore'": the page stays blank. React 19 has the hook built in, so the shim is
 * answered with a re-export from react. (The build converts CommonJS itself and doesn't need this.)
 */
export function useSyncExternalStoreDev(): Plugin {
  const id = "\0use-sync-external-store-shim";
  return {
    name: "suveryn-use-sync-external-store-dev",
    apply: "serve",
    enforce: "pre",
    resolveId: (source) => (/^use-sync-external-store\/shim(\/index\.js)?$/.test(source) ? id : null),
    load: (loaded) => (loaded === id ? `export { useSyncExternalStore } from "react";` : null),
  };
}

export default defineConfig({
  plugins: [
    reactAriaCsp(),
    useSyncExternalStoreDev(),
    // React Aria's own strings (e.g. a listbox's "selected") only in the UI's languages; it falls back
    // from en-GB, nl-BE and fr-BE to these by language.
    { ...optimizeLocales.vite({ locales: ["en-US", "nl-NL", "fr-FR"] }), enforce: "pre" },
    react(),
  ],
  server: {
    host: "127.0.0.1",
    // /auth: the sign-in routes; SUVERYN_PUBLIC_URL on the gateway must be this dev server's URL
    // (http://localhost:5173), because Keycloak redirects the browser back to /auth/callback here.
    proxy: { "/v1": api, "/health": api, "/auth": api },
  },
  // In development, React Aria is bundled by Vite's dependency optimiser rather than transformed per
  // file; leave it out of that so the CSP replacement above applies there too.
  optimizeDeps: { exclude: ["react-aria-components", "react-aria"] },
  build: {
    sourcemap: false,
    // Never inline assets as data: URLs: the CSP has no data: (docs/content-security-policy.md).
    assetsInlineLimit: 0,
    // Two entries: the chat (index.html) and the appliance's first-boot web setup (setup.html), which
    // shares the component library and nothing else: no sign-in, no chat code (suveryn-tracker#37, #44).
    rollupOptions: { input: { chat: resolve(import.meta.dirname, "index.html"), setup: resolve(import.meta.dirname, "setup.html") } },
  },
  test: { environment: "node" },
});
