// @vitest-environment node
/**
 * Review of the backup strategy (26 October 2026): the administrator tests the recovery key on the
 * Backups page, and is told outside it when backups need attention.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BackupBar } from "./BackupBar";

describe("backups that need an administrator's attention", () => {
  it("says why in a bar, with the way to the Backups page and a way to put it away", () => {
    const html = renderToStaticMarkup(<BackupBar reason="failing" onOpen={() => {}} onDismiss={() => {}} />);
    expect(html).toContain("Last night&#x27;s backup failed.");
    expect(html).toContain("Open Backups");
    expect(html).toContain('data-serious="true"');
    expect(renderToStaticMarkup(<BackupBar reason="key_due" onOpen={() => {}} onDismiss={() => {}} />)).not.toContain("data-serious");
  });
});
