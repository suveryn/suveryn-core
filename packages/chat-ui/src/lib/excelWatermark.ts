/**
 * The watermark of a strictly confidential case in an Excel file (docs/design/chat-ui.md §11;
 * suveryn-tracker#183). Three parts, so it shows on screen and on paper and isn't gone with two rows:
 *
 * - a picture behind the cells, Excel's own sheet background ("Page Layout › Background"): the label
 *   and the case, the person and the time, diagonal and light; Excel shows it on screen and doesn't print
 *   it (LibreOffice prints it);
 * - the line in every sheet's header and footer, on paper;
 * - the line as the first and last row of every sheet (lib/office.ts), seen wherever the file is opened.
 *
 * Nothing in a file can't be removed by whoever holds it; a mark names who exported it, it doesn't
 * prevent. The parts are written as the file format has them (ECMA-376 Part 1: a worksheet's
 * `headerFooter` and `picture`, in the order the standard gives them), through write-excel-file's own
 * extension point, its "features". Not taken: a picture in the header (`&G`), Microsoft's documented
 * watermark, which prints but shows only in the page layout view.
 */
import type { Feature } from "write-excel-file/browser";
import type { Watermark } from "./watermark";

type Utility = typeof import("write-excel-file/utility");

const RELATIONSHIP = "rId-suveryn-watermark";
const PICTURE = "xl/media/suveryn-watermark.png";
const IMAGE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image";

/** A header or footer's text: `&` starts a code there (`&C` centre, `&B` bold), so a literal one is
 *  doubled; Excel holds at most 255 characters, codes included. The longest start of the line that fits once
 *  doubled, so a cut never splits a doubled `&` and the person and the time at the end are kept where they fit. */
export function headerFooterText(line: string): string {
  let out = "";
  for (const ch of line) {
    const next = out + (ch === "&" ? "&&" : ch);
    if (next.length > 240) break;
    out = next;
  }
  return out;
}

/** The picture's second line: the watermark line without the label it starts with. */
export function pictureLine(w: Watermark): string {
  return w.line.startsWith(w.label) ? w.line.slice(w.label.length).replace(/^[\s·:–-]+/, "") : w.line;
}

/** The feature: the line in every sheet's header and footer, and, with a picture, the sheet background. */
export function excelWatermark(w: Watermark, picture: ArrayBuffer | undefined, u: Utility): Feature<ArrayBuffer> {
  const text = u.sanitizeTextContent(headerFooterText(w.line));
  const headerFooter = `<headerFooter><oddHeader>&amp;C&amp;B${text}</oddHeader><oddFooter>&amp;C${text}</oddFooter></headerFooter>`;
  const order = u.getOrderOfSiblings("xl/worksheets/sheet{id}.xml", "worksheet") ?? [];
  return {
    files: {
      transform: {
        "xl/worksheets/sheet{id}.xml": {
          transform: (xml) => {
            let out = xml.includes("<headerFooter") ? xml
              : u.insertElementMarkupAccordingToOrderOfSiblings(xml, headerFooter, order, "worksheet");
            if (picture && !out.includes("<picture "))
              out = u.insertElementMarkupAccordingToOrderOfSiblings(out, `<picture r:id="${RELATIONSHIP}"/>`, order, "worksheet");
            return out;
          },
        },
        ...(picture ? {
          "xl/worksheets/_rels/sheet{id}.xml.rels": {
            transform: (xml) => xml.includes(RELATIONSHIP) ? xml : xml.replace("</Relationships>",
              `<Relationship Id="${RELATIONSHIP}" Type="${IMAGE_TYPE}" Target="../media/suveryn-watermark.png"/></Relationships>`),
          },
          "[Content_Types].xml": {
            transform: (xml) => /Extension="png"/.test(xml) ? xml
              : xml.replace("</Types>", `<Default Extension="png" ContentType="image/png"/></Types>`),
          },
        } : {}),
      },
      ...(picture ? { write: { files: () => ({ [PICTURE]: picture }) } } : {}),
    },
  };
}

/** The picture: the label large and the line under it, diagonal, in `colour` (sRGB hex: the brand's
 *  confidential violet, light; lib/office.ts) on a clear ground. Made in the browser; undefined where there is
 *  no canvas (the tests), and the file then has the other two parts. */
export async function watermarkPicture(w: Watermark, colour: string): Promise<ArrayBuffer | undefined> {
  if (typeof OffscreenCanvas === "undefined") return undefined;
  const canvas = new OffscreenCanvas(1200, 800);
  const g = canvas.getContext("2d");
  if (!g) return undefined;
  g.translate(600, 400);
  g.rotate(-Math.PI / 6);
  g.fillStyle = `#${colour}`;
  g.textAlign = "center";
  g.font = "600 72px Inter, sans-serif";
  g.fillText(w.label, 0, -10, 1100);
  g.font = "500 34px Inter, sans-serif";
  g.fillText(pictureLine(w), 0, 58, 1100);
  const blob = await canvas.convertToBlob({ type: "image/png" });
  return blob.arrayBuffer();
}
