/** Media queries a component needs to know about in its code, not only in CSS. */
import { useEffect, useState } from "react";

/** Below this width the column is a drawer and the composer one pill (docs/design/chat-ui.md §2). */
export const NARROW = "(max-width: 767px)";

/** Whether `query` matches now, following the window as it changes. */
export function useMedia(query: string): boolean {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const change = () => setMatches(list.matches);
    change();
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  }, [query]);
  return matches;
}
