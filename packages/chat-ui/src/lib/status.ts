/**
 * What the waiting indicator says (suveryn-tracker#6). Each text matches a real step the server
 * reports in a `status` event; nothing is shown that the pipeline isn't actually doing.
 */
import type { StreamStatus } from "../api";
import { t } from "../i18n";
import { modelName } from "./model";

export function statusText(status: StreamStatus | undefined): string | null {
  if (!status) return null;
  const m = t();
  switch (status.step) {
    case "searching":
      return m.statusSearching;
    case "reading": {
      const passages = m.passages(status.passages ?? 0);
      return status.complete ? m.statusReadingAll(passages) : m.statusReadingBest(passages);
    }
    case "loading_model":
      return m.statusLoading(modelName(status.model)?.full ?? null);
    case "writing":
      return m.statusWriting;
    default:
      return null;
  }
}
