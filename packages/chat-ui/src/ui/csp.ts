/**
 * Keeps React Aria within the appliance's Content-Security-Policy (style-src 'self', no
 * 'unsafe-inline'; appliance reverse-proxy/suveryn-csp.conf).
 *
 * React Aria writes one <style> element of its own, the first time anything pressable renders: a
 * touch-action rule for [data-react-aria-pressable] (usePress). The policy blocks inline <style>, and
 * the browser reports a violation. React Aria skips writing it when an element with its id is
 * already in the document, so this module puts a placeholder with that id in <head>, and ui.css
 * carries the same rule instead. The other <style> React Aria can write (usePreventScroll, iPhone and
 * iPad only, while a menu or dialog is open) is replaced at build time: see vite.config.ts.
 *
 * Imported for its effect by src/ui/index.ts, before any component renders.
 */
export const PRESSABLE_STYLE_ID = "react-aria-pressable-style";

if (typeof document !== "undefined" && !document.getElementById(PRESSABLE_STYLE_ID)) {
  const placeholder = document.createElement("meta");
  placeholder.id = PRESSABLE_STYLE_ID;
  placeholder.name = "react-aria-pressable-style";
  placeholder.content = "in ui.css";
  document.head.append(placeholder);
}
