/**
 * Brings a screen into the state a board shows, the way a person gets there: clicks, typing, a key.
 * Each step waits (up to three seconds) for what it names to appear. A step that finds nothing says so in
 * the console and the preview shows how far it got.
 */
import { useEffect, type ReactNode } from "react";

export type Step =
  | { click: string; within?: string; nth?: number }   // a control by its name (aria-label or its text), in a region named `within`
  | { type: string; into: string }                    // text into a field, by its label or placeholder
  | { key: string }                                   // a key on what has the focus ("Tab", "Escape")
  | { hover: string }
  | { drop: string[] }                                 // files chosen in the file picker, by name (board G13; fakeApi.ts answers them)
  | { wait: number };

const CONTROLS = 'button, a[href], [role="button"], [role="menuitem"], [role="menuitemradio"], [role="option"], [role="row"], [role="tab"], [role="link"], [role="treeitem"], summary, label';

const nameOf = (el: Element) => (el.getAttribute("aria-label") ?? el.textContent ?? "").replace(/\s+/g, " ").trim();
const visible = (el: Element) => !!(el as HTMLElement).offsetParent || getComputedStyle(el).position === "fixed";

function find(name: string, within?: string, nth = 0): HTMLElement | null {
  let root: ParentNode = document;
  if (within) {
    const region = [...document.querySelectorAll("[aria-label], [role=dialog], [role=alertdialog], nav, aside, main, header")]
      .find((r) => nameOf(r).startsWith(within) || r.getAttribute("aria-label") === within);
    if (!region) return null;
    root = region;
  }
  const all = [...root.querySelectorAll(CONTROLS)].filter(visible);
  const exact = all.filter((el) => nameOf(el) === name);
  const loose = exact.length ? exact : all.filter((el) => nameOf(el).startsWith(name));
  return (loose[nth] as HTMLElement) ?? null;
}

function field(label: string): HTMLInputElement | HTMLTextAreaElement | null {
  const byPlaceholder = document.querySelector<HTMLInputElement>(`input[placeholder^="${label}"], textarea[placeholder^="${label}"]`);
  if (byPlaceholder) return byPlaceholder;
  const byLabel = [...document.querySelectorAll("label")].find((l) => nameOf(l) === label);
  const id = byLabel?.getAttribute("for");
  return (id ? document.getElementById(id) : null) as HTMLInputElement | null
    ?? document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`);
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitFor<T>(get: () => T | null): Promise<T | null> {
  for (let i = 0; i < 30; i++) { const v = get(); if (v) return v; await pause(100); }
  return null;
}

/** Sets a React-controlled field's value as typing would. */
function typeInto(el: HTMLInputElement | HTMLTextAreaElement, text: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, text);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function pointer(el: HTMLElement, types: string[]) {
  const r = el.getBoundingClientRect();
  const at = { bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, pointerType: "mouse", button: 0, isPrimary: true };
  for (const t of types) el.dispatchEvent(t.startsWith("pointer") ? new PointerEvent(t, at) : new MouseEvent(t, at));
}

export async function play(steps: Step[]): Promise<void> {
  await pause(400); // the screen's first data
  for (const s of steps) {
    if ("wait" in s) { await pause(s.wait); continue; }
    if ("key" in s) {
      const target = (document.activeElement ?? document.body) as HTMLElement;
      target.dispatchEvent(new KeyboardEvent("keydown", { key: s.key, bubbles: true }));
      target.dispatchEvent(new KeyboardEvent("keyup", { key: s.key, bubbles: true }));
      await pause(150);
      continue;
    }
    if ("drop" in s) {
      const input = await waitFor(() => document.querySelector<HTMLInputElement>('input[type="file"]'));
      if (!input) { console.warn("preview: no file picker"); return; }
      const files = new DataTransfer();
      for (const name of s.drop) files.items.add(new File(["sample"], name));
      input.files = files.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await pause(400);
      continue;
    }
    if ("type" in s) {
      const el = await waitFor(() => field(s.into));
      if (!el) { console.warn(`preview: no field "${s.into}"`); return; }
      el.focus();
      typeInto(el, s.type);
      await pause(150);
      continue;
    }
    const name = "click" in s ? s.click : (s as { hover: string }).hover;
    const el = await waitFor(() => find(name, "click" in s ? s.within : undefined, "click" in s ? s.nth : 0));
    if (!el) { console.warn(`preview: nothing named "${name}"`); return; }
    if ("hover" in s) pointer(el, ["pointerover", "pointerenter", "mouseover", "mouseenter", "pointermove"]);
    // As a mouse does: React Aria then shows no keyboard focus ring, as for a person clicking.
    else { pointer(el, ["pointerover", "pointerenter", "pointerdown", "mousedown"]); pointer(el, ["pointerup", "mouseup", "click"]); }
    await pause(250);
  }
}

let started = false;
/** Whether a preview's steps have started (main.tsx then leaves "ready" to them). */
export const stepsRunning = () => started;
export function Steps({ steps, children }: { steps: Step[]; children: ReactNode }) {
  useEffect(() => {
    if (started) return; // StrictMode runs effects twice in development
    started = true;
    play(steps).finally(() => document.documentElement.setAttribute("data-preview-ready", ""));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once, on arrival
  return <>{children}</>;
}
