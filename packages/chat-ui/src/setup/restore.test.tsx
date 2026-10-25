// @vitest-environment node
/**
 * Restoring a backup from the web setup (suveryn-tracker#56): what the screens say, that every language
 * has the restore's codes, and the stand-in appliance's restore from check to done.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { TEXT } from "./i18n";
import { madeAt, RestoreConfirm, RestoreDone, RestoreSource } from "./steps/Restore";
import { Welcome } from "./steps/Welcome";

const STATE = { name: "suveryn-4f2a", answers: {}, usb_disks: [], restore: null } as never;
const BACKUP = { file: "suveryn-backup_notary-brussels-01_20261023T023000Z.tar.zst.age", created: "2026-10-23T02:30:00Z",
                 appliance: "notary-brussels-01" };

describe("restoring a backup from the web setup", () => {
  it("is offered on the welcome screen", () => {
    const html = renderToStaticMarkup(<Welcome onStart={() => {}} onRestore={() => {}} headingId="h" />);
    expect(html).toContain("Restore from a backup");
  });

  it("asks where the backups are and for the key, and never says the disk is erased", () => {
    const html = renderToStaticMarkup(<RestoreSource state={STATE} onBack={() => {}} onChecking={() => {}} headingId="h" />);
    expect(html).toContain("Where the backups are");
    expect(html).toContain("Recovery key");
    expect(html).not.toContain("erased");
  });

  it("says why the last check failed", () => {
    const state = { ...(STATE as object), restore: { state: "failed", error: "wrong_key" } } as never;
    const html = renderToStaticMarkup(<RestoreSource state={state} onBack={() => {}} onChecking={() => {}} headingId="h" />);
    expect(html).toContain("No backup could be restored");
    expect(html).toContain("open this backup");
  });

  it("shows the backup found and the name the appliance takes before anything is replaced", () => {
    const html = renderToStaticMarkup(<RestoreConfirm state={STATE} initial={{ state: "checked", backup: BACKUP }}
                                                      onBack={() => {}} onStart={() => {}} headingId="h" />);
    expect(html).toContain("notary-brussels-01.local");
    expect(html).toContain("it takes the name notary-brussels-01");
    expect(html).toContain("23 October 2026");
    expect(html).toContain("Turn the old appliance off");
  });

  it("ends at the old appliance's address", () => {
    const html = renderToStaticMarkup(<RestoreDone restore={{ state: "done", backup: BACKUP, address: "https://notary-brussels-01.local",
                                                              steps: [] }} headingId="h" />);
    expect(html).toContain("https://notary-brussels-01.local");
  });

  it("formats when a backup was made in each language, and leaves a date it can't read as it is", () => {
    expect(madeAt("2026-10-23T02:30:00Z", "nl-BE")).toContain("oktober 2026");
    expect(madeAt("2026-10-23T02:30:00Z", "fr-BE")).toContain("octobre 2026");
    expect(madeAt("yesterday", "en-GB")).toBe("yesterday");
  });

  it("has every code the appliance answers a restore with, in every language", () => {
    for (const t of Object.values(TEXT)) {
      for (const code of ["wrong_key", "no_backup", "unreachable", "damaged", "newer", "invalid", "restore"]) expect(t.restoreErrors[code]).toBeTruthy();
      for (const code of ["key_invalid", "restore_started", "not_checked", "disk_gone", "address"]) expect(t.errors[code]).toBeTruthy();
    }
  });
});

describe("the stand-in appliance's restore", () => {
  it("checks, then restores step by step to the old appliance's address", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { answer } = await import("./demo");
    const key = `# Sūveryn backup recovery key\nAGE-SECRET-KEY-1${"Q".repeat(58)}\n`;
    await expect(answer("PUT", "answers/restore", { target: "usb", disk: "x", key: "not a key" })).rejects.toThrow("key_invalid");
    await expect(answer("POST", "restore/start")).rejects.toThrow("not_checked");
    expect(await answer("PUT", "answers/restore", { target: "usb", disk: "x", key })).toEqual({ state: "checking" });
    vi.setSystemTime(Date.now() + 2500);
    expect(await answer("GET", "restore")).toMatchObject({ state: "checked", backup: { appliance: "notary-brussels-01" } });
    expect(await answer("POST", "restore/start")).toMatchObject({ state: "restoring" });
    vi.setSystemTime(Date.now() + 8000);
    expect(await answer("GET", "restore")).toMatchObject({ state: "done", address: "https://notary-brussels-01.local" });
    vi.useRealTimers();
  });
});
