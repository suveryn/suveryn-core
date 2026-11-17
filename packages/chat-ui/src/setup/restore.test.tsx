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
    const state = { ...(STATE as object), restore: { state: "failed", message: { kind: "refused", code: "backup.key_mismatch", params: {} } } } as never;
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

  it("offers the dates of the backups the key opens, the newest chosen", () => {
    const choices = [{ ...BACKUP, size: 2 }, { ...BACKUP, file: BACKUP.file.replace("20261023", "20261016"), created: "2026-10-16T02:30:00Z", size: 1 }];
    const html = renderToStaticMarkup(<RestoreConfirm state={STATE} initial={{ state: "checked", backup: BACKUP, choices }}
                                                      onBack={() => {}} onStart={() => {}} headingId="h" />);
    expect(html).toContain("Backup to restore");
    expect(html).toContain("23 October 2026");
    const one = renderToStaticMarkup(<RestoreConfirm state={STATE} initial={{ state: "checked", backup: BACKUP, choices: [choices[0]] }}
                                                     onBack={() => {}} onStart={() => {}} headingId="h" />);
    expect(one).not.toContain("Backup to restore");  // nothing to choose
  });

  it("says when the newest backup is damaged and the newest whole one is shown instead (suveryn-tracker#166)", () => {
    const older = { ...BACKUP, file: BACKUP.file.replace("20261023", "20261016"), created: "2026-10-16T02:30:00Z" };
    const oldest = { ...BACKUP, file: BACKUP.file.replace("20261023", "20261009"), created: "2026-10-09T02:30:00Z", size: 1 };
    const warning = { kind: "warning", code: "backup.newest_damaged", params: { newest: "2026-10-23T02:30:00Z", whole: "2026-10-16T02:30:00Z" } };
    const html = renderToStaticMarkup(<RestoreConfirm state={STATE} initial={{ state: "checked", backup: older, choices: [{ ...older, size: 1 }, oldest], warning }}
                                                      onBack={() => {}} onStart={() => {}} headingId="h" />);
    expect(html).toContain("The newest backup there, made on 23 October 2026");
    expect(html).toContain("is damaged. The newest whole backup, made on 16 October 2026");
    expect(html).toContain("(newest whole)");  // the backup offered, in the picker
    const plain = renderToStaticMarkup(<RestoreConfirm state={STATE} initial={{ state: "checked", backup: BACKUP }}
                                                       onBack={() => {}} onStart={() => {}} headingId="h" />);
    expect(plain).not.toContain("is damaged");
  });

  it("says from when to when the backups a restore tried are damaged, and a plain sentence without the dates", () => {
    const dated = { ...(STATE as object), restore: { state: "failed", message: { kind: "refused", code: "backup.damaged",
      params: { newest: "2026-10-23T02:30:00Z", oldest: "2026-10-20T02:30:00Z" } } } } as never;
    const html = renderToStaticMarkup(<RestoreSource state={dated} onBack={() => {}} onChecking={() => {}} headingId="h" />);
    expect(html).toContain("made from 20 October 2026");
    expect(html).toContain("to 23 October 2026");
    const plain = { ...(STATE as object), restore: { state: "failed", message: { kind: "refused", code: "backup.damaged", params: {} } } } as never;
    expect(renderToStaticMarkup(<RestoreSource state={plain} onBack={() => {}} onChecking={() => {}} headingId="h" />))
      .toContain("The newest backup there is damaged");
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
      for (const code of ["backup.key_mismatch", "backup.not_found", "backup.target_unreachable", "backup.damaged", "backup.version_too_new",
        "backup.restore_failed", "backup.not_a_key", "setup.restore_started", "setup.backup_not_checked", "backup.disk_gone", "backup.share_address_invalid"]) {
        expect((t.messages as Record<string, unknown>)[code], code).toBeTruthy();
      }
      expect(t.messages["request.invalid"]).toBeTruthy();  // answers that were incomplete
    }
  });
});

describe("the stand-in appliance's restore", () => {
  it("checks, then restores step by step to the old appliance's address", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { answer } = await import("./demo");
    const key = `# Sūveryn backup recovery key\nAGE-SECRET-KEY-1${"Q".repeat(58)}\n`;
    await expect(answer("PUT", "answers/restore", { target: "usb", disk: "x", key: "not a key" })).rejects.toThrow("backup.not_a_key");
    await expect(answer("POST", "restore/start")).rejects.toThrow("setup.backup_not_checked");
    expect(await answer("PUT", "answers/restore", { target: "usb", disk: "x", key })).toEqual({ state: "checking" });
    vi.setSystemTime(Date.now() + 2500);
    expect(await answer("GET", "restore")).toMatchObject({ state: "checked", backup: { appliance: "notary-brussels-01" } });
    const checked = await answer("GET", "restore") as { choices: { file: string; created: string }[] };
    await expect(answer("POST", "restore/start", { file: "suveryn-backup_other_20261024T023000Z.tar.zst.age" })).rejects.toThrow();
    expect(await answer("POST", "restore/start", { file: checked.choices[3].file }))
      .toMatchObject({ state: "restoring", backup: { created: "2026-10-16T02:30:00Z" } });  // a week earlier
    vi.setSystemTime(Date.now() + 8000);
    expect(await answer("GET", "restore")).toMatchObject({ state: "done", address: "https://notary-brussels-01.local" });
    vi.useRealTimers();
  });
});
