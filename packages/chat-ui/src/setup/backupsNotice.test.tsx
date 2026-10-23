// @vitest-environment node
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Backups } from "./steps/Backups";

describe("the backup step", () => {
  it("no longer says backups aren't made: the appliance makes them (suveryn-tracker#33)", () => {
    const state = { answers: {}, usb_disks: [] } as never;
    const html = renderToStaticMarkup(<Backups state={state} onBack={() => {}} onDone={() => {}} headingId="h" />);
    expect(html).not.toContain("made yet");
    expect(html).toContain("Where the appliance writes its backups");
  });
});
