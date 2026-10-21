// @vitest-environment node
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Backups } from "./steps/Backups";

describe("the backup step (audit of 21 October 2026, finding 2)", () => {
  it("says backups aren't made yet, before anything is chosen", () => {
    const state = { answers: {}, usb_disks: [] } as never;
    const html = renderToStaticMarkup(<Backups state={state} onBack={() => {}} onDone={() => {}} headingId="h" />);
    expect(html).toContain("Backups aren&#x27;t made yet");
    expect(html.indexOf("made yet")).toBeLessThan(html.indexOf('role="radiogroup"'));
  });
});
