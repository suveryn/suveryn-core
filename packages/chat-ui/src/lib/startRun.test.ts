import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError, startRun } from "../api";
import { liveRunInstead } from "./navigation";

afterEach(() => vi.unstubAllGlobals());

/** suveryn-tracker#181: two playbooks live in one case. Starting the second again is refused with the run the
 *  gateway names; that one is opened, never the case's other live run. */
describe("a second start of a playbook that is already going", () => {
  it("carries the run the gateway names, from its Problem Details to the run that opens", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      type: "about:blank", status: 409, kind: "refused", code: "run.already_going", params: { run: "r-company-formation" },
      title: "A run of this playbook is live in this case: `run`.",
    }), { status: 409, headers: { "Content-Type": "application/problem+json" } })));
    const error = await startRun("case-1", "company-formation", "nl").catch((e) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect(liveRunInstead((error as HttpError).problem)).toBe("r-company-formation");   // not the deed intake's live run
  });

  it("opens nothing on another refusal, or an answer that isn't the gateway's own", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Bad gateway</html>", { status: 409 })));
    const error = await startRun("case-1", "deed-intake", "nl").catch((e) => e);
    expect(liveRunInstead((error as HttpError).problem)).toBeNull();
  });
});
