// @vitest-environment node
/**
 * Board G13: the upload cards say why a page needs checking, count the pages recognised, and delete only through
 * the worded link; the × takes a file out of the question.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import en from "../i18n/en";
import { markOrigin } from "../lib/marks";
import type { Attachment } from "../types";
import { AttachmentCard } from "./Chips";

const none = () => {};
const card = (a: Partial<Attachment>, extra: { onDelete?: () => void; onUseAsSource?: () => void } = {}) =>
  renderToStaticMarkup(<AttachmentCard a={{ key: "k", filename: "deed.pdf", status: "ready", ...a } as Attachment} onRemove={none} {...extra} />);

describe("the cards of an upload (board G13)", () => {
  it("says why a page needs checking", () => {
    expect(card({ status: "needs_review", reviewPages: [2], reviewKind: "page_coverage_low" })).toContain("Usable · check p. 2 (hard to read)");
    expect(card({ status: "needs_review", reviewPages: [2] })).toContain("Usable · check p. 2<");  // a kind without words: no brackets
  });
  it("counts the pages recognised, not the one being worked on", () => {
    expect(card({ status: "processing", reading: { step: "ocr", done: 4, total: 12 } })).toContain("Recognising text · page 4 of 12");
    expect(card({ status: "processing", reading: { step: "ocr", done: 0, total: 12 } })).toContain(">Recognising text<");
  });
  it("says where sūveryn's own answer came from; one button, and deleting only through the worded link", () => {
    const html = card({ status: "noticed", filename: "Terms.docx",
                        noticed: { ref: "A-7c21e04d", kind: "answer", line: "Made by sūveryn: answer from case 124, 17/10/2026 · sūveryn-ref A-7c21e04d" } },
                      { onDelete: none, onUseAsSource: none });
    const esc = (t: string) => t.replace(/'/g, "&#x27;");
    expect(html).toContain(esc(`${en.noticedTitle("answer")} (case 124, 17 Oct). ${en.cardNoticedNotSource}`));
    expect(html.match(/<button/g)?.length).toBe(3);   // the ×, Use as a source anyway, and the link
    expect(html).toContain(`>${en.deleteUpload}</`);
    expect(html).toContain(en.removeFromQuestion("Terms.docx"));  // the × takes it out of the question, never deletes
  });
  it("offers the same quiet delete link on a card that couldn't be read, saying the case in a case", () => {
    const html = renderToStaticMarkup(<AttachmentCard a={{ key: "k", filename: "scan.pdf", status: "failed" } as Attachment}
                                                      onRemove={none} onReplace={none} onDelete={none} inCase />);
    expect(html).toContain(`>${en.anotherFile}</`);
    expect(html).toContain(`class="ui-link-button card-attachment-delete"`);
    expect(html).toContain(`>${en.deleteUploadFromCase}</`);
  });
  it("reads the case and the date from a mark in any language", () => {
    expect(markOrigin("Gemaakt door sūveryn: antwoord uit dossier 124, 17-10-2026 · sūveryn-ref A-1")).toMatchObject({ caseRef: "124" });
    expect(markOrigin("Créé par sūveryn : réponse du dossier 2026/0611, 19/10/2026 · sūveryn-ref A-1")?.date?.getDate()).toBe(19);
    expect(markOrigin("Made by sūveryn: answer, 19/10/2026 · sūveryn-ref A-1")).toBeNull();  // a personal chat: no case
  });
});
