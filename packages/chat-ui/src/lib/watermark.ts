/**
 * The watermark on every export from a strictly confidential case (docs/design/chat-ui.md §11):
 * "STRICTLY CONFIDENTIAL" across every page of a Word file, and one line naming the case, the person
 * and the time on every export, so whoever leaks a file is named on it. Made at the moment of the
 * download, in the interface language; the date the Belgian way (21/10/2026 14:32).
 */
import { createContext, useContext } from "react";
import type { Messages } from "../i18n/en";
import * as fmt from "../i18n/format";

export type Watermark = {
  /** Across the page: "STRICTLY CONFIDENTIAL". */
  label: string;
  /** "STRICTLY CONFIDENTIAL · case 125 · Name · 21/10/2026 14:32". */
  line: string;
};

export function watermark(kase: { reference: string; confidential?: boolean } | null, who: string, m: Messages,
                          locale: string, now: Date = new Date()): Watermark | undefined {
  if (!kase?.confidential) return undefined;
  const date = fmt.dateInTwoDigits(now, locale);
  const time = fmt.time(now, locale);
  return { label: m.watermarkLabel, line: m.watermarkLine({ ref: kase.reference, who, when: `${date} ${time}` }) };
}

/** A text file's first line: the watermark, then an empty line. */
export function withWatermark(text: string, w: Watermark | undefined): string {
  return w ? `${w.line}\n\n${text}` : text;
}

/** The open case's watermark, made at the moment of an export; undefined outside a strictly
 *  confidential case. Provided by the app around the conversation and the playbook view, read by
 *  every download button (``useWatermark``). */
export const WatermarkContext = createContext<() => Watermark | undefined>(() => undefined);
export const useWatermark = () => useContext(WatermarkContext);
