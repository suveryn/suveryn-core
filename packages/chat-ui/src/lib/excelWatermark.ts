/**
 * The watermark of a strictly confidential case in an Excel file (docs/design/chat-ui.md §11;
 * suveryn-tracker#183, #184). Four parts, so it shows on screen and on paper and isn't gone with two rows:
 *
 * - a picture behind the cells, Excel's own sheet background ("Page Layout › Background"): the label
 *   and the case, the person and the time, diagonal and light; Excel shows it on screen and doesn't print it;
 * - the same picture, page-shaped, in every sheet's header (`&G`, "Header & Footer › Picture"): Microsoft's
 *   own way to print a watermark from Excel, on every page; on screen only in the page layout view;
 * - the line in every sheet's header and footer, on paper;
 * - the line as the first and last row of every sheet (lib/office.ts), seen wherever the file is opened.
 *
 * Nothing in a file can't be removed by whoever holds it; a mark names who exported it, it doesn't
 * prevent. The parts are written as the file format has them (ECMA-376 Part 1: a worksheet's
 * `headerFooter`, `legacyDrawingHF` and `picture`, in the order the standard gives them; the header's
 * picture as a VML drawing, as Excel and XlsxWriter write it), through write-excel-file's own extension
 * point, its "features".
 */
import type { Feature } from "write-excel-file/browser";
import type { Watermark } from "./watermark";

type Utility = typeof import("write-excel-file/utility");

const RELATIONSHIP = "rId-suveryn-watermark";
const HEADER_RELATIONSHIP = "rId-suveryn-watermark-header";
const PICTURE = "xl/media/suveryn-watermark.png";
const PAPER_PICTURE = "xl/media/suveryn-watermark-paper.png";
const RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const IMAGE_TYPE = `${RELS}/image`;
const VML_TYPE = `${RELS}/vmlDrawing`;
const headerDrawing = (sheetId: string) => `xl/drawings/suveryn-watermark-header${sheetId}.vml`;

/** A picture's size in pixels: the sheet background's, landscape like a screen, and the header's, shaped
 *  like the printable part of an A4 or Letter page (495 by 693 points), so it covers the page. */
export type PictureSize = { width: number; height: number };
export const SCREEN: PictureSize = { width: 1200, height: 800 };
export const PAPER: PictureSize = { width: 900, height: 1260 };
const PAPER_POINTS = { width: 495, height: Math.round(495 * PAPER.height / PAPER.width) };

/** The two pictures; either can be missing (no canvas), and the file then has the other parts. */
export type WatermarkPictures = { screen?: ArrayBuffer; paper?: ArrayBuffer };

/** A header or footer's text: `&` starts a code there (`&C` centre, `&B` bold), so a literal one is doubled;
 *  Excel holds at most 255 characters, codes included, and "&L&G&C&B" comes before it. The longest start of
 *  the line that fits once doubled, so a cut never splits a doubled `&` and the person and the time at the
 *  end are kept where they fit. */
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

/** The feature: the line in every sheet's header and footer and, with the pictures, the sheet background
 *  and the picture in the header. */
export function excelWatermark(w: Watermark, pictures: WatermarkPictures, u: Utility): Feature<ArrayBuffer> {
  const text = u.sanitizeTextContent(headerFooterText(w.line));
  const { screen, paper } = pictures;
  // The printed picture in the header's left part: it is as wide as the page's printable part, so it starts
  // at the left margin and covers the page; the line stays in the centre.
  const header = `${paper ? "&amp;L&amp;G" : ""}&amp;C&amp;B${text}`;
  const headerFooter = `<headerFooter><oddHeader>${header}</oddHeader><oddFooter>&amp;C${text}</oddFooter></headerFooter>`;
  // write-excel-file's list of a worksheet's elements leaves out `legacyDrawingHF`; the standard has it
  // after `legacyDrawing`, before `picture`.
  const order = [...(u.getOrderOfSiblings("xl/worksheets/sheet{id}.xml", "worksheet") ?? [])];
  const at = order.indexOf("legacyDrawing");
  if (at >= 0) order.splice(at + 1, 0, "legacyDrawingHF", "drawingHF");
  const relationship = (id: string, type: string, target: string) => `<Relationship Id="${id}" Type="${type}" Target="${target}"/>`;
  return {
    files: {
      transform: {
        "xl/worksheets/sheet{id}.xml": {
          transform: (xml) => {
            let out = xml.includes("<headerFooter") ? xml
              : u.insertElementMarkupAccordingToOrderOfSiblings(xml, headerFooter, order, "worksheet");
            if (screen && !out.includes("<picture "))
              out = u.insertElementMarkupAccordingToOrderOfSiblings(out, `<picture r:id="${RELATIONSHIP}"/>`, order, "worksheet");
            if (paper && !out.includes("<legacyDrawingHF "))
              out = u.insertElementMarkupAccordingToOrderOfSiblings(out, `<legacyDrawingHF r:id="${HEADER_RELATIONSHIP}"/>`, order, "worksheet");
            return out;
          },
        },
        ...(screen || paper ? {
          "xl/worksheets/_rels/sheet{id}.xml.rels": {
            transform: (xml, _o, { sheetId }) => xml.replace("</Relationships>",
              (screen && !xml.includes(`"${RELATIONSHIP}"`) ? relationship(RELATIONSHIP, IMAGE_TYPE, "../media/suveryn-watermark.png") : "")
              + (paper && !xml.includes(`"${HEADER_RELATIONSHIP}"`)
                ? relationship(HEADER_RELATIONSHIP, VML_TYPE, `../drawings/suveryn-watermark-header${sheetId}.vml`) : "")
              + "</Relationships>"),
          },
          "[Content_Types].xml": {
            transform: (xml) => xml.replace("</Types>",
              (/Extension="png"/.test(xml) ? "" : `<Default Extension="png" ContentType="image/png"/>`)
              + (paper && !/Extension="vml"/.test(xml) ? `<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>` : "")
              + "</Types>"),
          },
        } : {}),
      },
      ...(screen || paper ? { write: { files: (sheets) => {
        const files: Record<string, ArrayBuffer | string> = {};
        if (screen) files[PICTURE] = screen;
        if (paper) {
          files[PAPER_PICTURE] = paper;
          sheets.forEach((_, i) => {
            const id = String(i + 1);  // write-excel-file's sheet ids: 1, 2, 3…
            files[headerDrawing(id)] = headerVml(id, u.sanitizeAttributeValue(w.label));
            files[headerDrawing(id).replace("drawings/", "drawings/_rels/") + ".rels"] =
              `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
              + relationship("rId1", IMAGE_TYPE, "../media/suveryn-watermark-paper.png") + "</Relationships>";
          });
        }
        return files;
      } } } : {}),
    },
  };
}

/** The header's picture as Excel writes one (a VML shape named for its place, `LH`: the header's left part),
 *  the page's printable size; one drawing per sheet, its shape ids in that sheet's own range. */
function headerVml(sheetId: string, title: string): string {
  return `<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">`
    + `<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="${sheetId}"/></o:shapelayout>`
    + `<v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75" o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">`
    + `<v:stroke joinstyle="miter"/><v:formulas>`
    + ["if lineDrawn pixelLineWidth 0", "sum @0 1 0", "sum 0 0 @1", "prod @2 1 2", "prod @3 21600 pixelWidth", "prod @3 21600 pixelHeight",
       "sum @0 0 1", "prod @6 1 2", "prod @7 21600 pixelWidth", "sum @8 21600 0", "prod @7 21600 pixelHeight", "sum @10 21600 0"]
      .map((e) => `<v:f eqn="${e}"/>`).join("")
    + `</v:formulas><v:path o:extrusionok="f" gradientshapeok="t" o:connecttype="rect"/><o:lock v:ext="edit" aspectratio="t"/></v:shapetype>`
    + `<v:shape id="LH" o:spid="_x0000_s${Number(sheetId) * 1024 + 1}" type="#_x0000_t75" `
    + `style="position:absolute;margin-left:0;margin-top:0;width:${PAPER_POINTS.width}pt;height:${PAPER_POINTS.height}pt;z-index:1">`
    + `<v:imagedata o:relid="rId1" o:title="${title}"/><o:lock v:ext="edit" rotation="t"/></v:shape></xml>`;
}

/** The picture: the label large and the line under it, diagonal, in `colour` (sRGB hex: the brand's
 *  confidential violet, light; lib/office.ts) on a clear ground, `size` in pixels (SCREEN or PAPER). Made in the
 *  browser; undefined where there is no canvas (the tests), and the file then has the other parts. */
export async function watermarkPicture(w: Watermark, colour: string, size: PictureSize = SCREEN): Promise<ArrayBuffer | undefined> {
  if (typeof OffscreenCanvas === "undefined") return undefined;
  const canvas = new OffscreenCanvas(size.width, size.height);
  const g = canvas.getContext("2d");
  if (!g) return undefined;
  g.translate(size.width / 2, size.height / 2);
  g.rotate(-Math.PI / 6);
  g.fillStyle = `#${colour}`;
  g.textAlign = "center";
  const k = size.width / SCREEN.width;  // the letters in proportion to the picture, so they aren't squeezed
  g.font = `600 ${Math.round(72 * k)}px Inter, sans-serif`;
  g.fillText(w.label, 0, -10 * k, size.width - 100);
  g.font = `500 ${Math.round(34 * k)}px Inter, sans-serif`;
  g.fillText(pictureLine(w), 0, 58 * k, size.width - 100);
  const blob = await canvas.convertToBlob({ type: "image/png" });
  return blob.arrayBuffer();
}
