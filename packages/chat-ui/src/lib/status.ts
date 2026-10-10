/**
 * What the waiting indicator says (suveryn-tracker#6). Each text matches a real step the server
 * reports in a `status` event; nothing is shown that the pipeline isn't actually doing.
 */
import type { StreamStatus } from "../api";
import { modelName } from "./model";

export function statusText(status: StreamStatus | undefined): string | null {
  if (!status) return null;
  switch (status.step) {
    case "searching":
      return "Searching your documents…";
    case "reading": {
      const n = status.passages ?? 0;
      const passages = `${n} ${n === 1 ? "passage" : "passages"}`;
      return status.complete ? `Reading your documents (${passages})…` : `Reading the ${passages} that best match your question…`;
    }
    case "loading_model":
      return `Loading ${modelName(status.model)?.full ?? "the model"}, which can take up to half a minute…`;
    case "writing":
      return "Writing the answer…";
    default:
      return null;
  }
}
