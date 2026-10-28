// @vitest-environment node
/**
 * Administration's side menu (docs/design/admin.md, artboard 30): two groups, Status first, the active item
 * marked as the current page; navigation in ink, never orange.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AdminView } from "./Admin";

describe("Administration", () => {
  it("opens on Status, with the menu in two groups", () => {
    const html = renderToStaticMarkup(<AdminView onBack={() => {}} />);
    expect(html.indexOf("Office")).toBeLessThan(html.indexOf("Appliance"));
    for (const item of ["Cases", "Playbooks", "Usage", "Status", "Backups"]) expect(html).toContain(`>${item}</span>`);
    expect(html).toMatch(/aria-current="page"[^>]*>.*?Status/);
    expect(html).toContain('<h1 class="admin-page-title">Status</h1>');
  });

  it("opens the page it is asked for", () => {
    const html = renderToStaticMarkup(<AdminView onBack={() => {}} initialPage="backups" />);
    expect(html).toContain('<h1 class="admin-page-title">Backups</h1>');
  });
});
