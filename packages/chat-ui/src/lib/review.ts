/** Wording for documents in needs_review: usable, but text on some pages may be missing. */
import { t } from "../i18n";

/** "p. 1" or "pp. 1, 3" (in the current language) */
export const pageList = (pages: number[]) => t().pageList(pages);

export const reviewHint = (pages: number[] | undefined): string => t().reviewHint(pages);
