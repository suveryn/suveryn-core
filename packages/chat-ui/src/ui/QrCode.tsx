/**
 * A QR code drawn as SVG elements in the page (suveryn-tracker#35, #37): never an image from a data:
 * URL, which the appliance's CSP refuses (img-src 'self'; docs/content-security-policy.md). The code's
 * modules come from qrcode-generator (MIT); only its matrix is used, none of its HTML or image output.
 * Dark modules on white with a quiet zone of 4, as phone cameras expect, whatever the page's colours.
 */
import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** The dark modules of a QR code for `text` (error correction M), as one SVG path, and its size. */
export function qrPath(text: string): { size: number; d: string } {
  const qr = qrcode(0, "M");
  qr.addData(text, "Byte");
  qr.make();
  const n = qr.getModuleCount();
  const parts: string[] = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) if (qr.isDark(r, c)) parts.push(`M${c + 4} ${r + 4}h1v1h-1z`);
  }
  return { size: n + 8, d: parts.join("") };
}

export function QrCode({ text, label, size = 136 }: { text: string; label: string; size?: number }) {
  const { size: n, d } = useMemo(() => qrPath(text), [text]);
  return (
    <svg className="ui-qr" role="img" aria-label={label} width={size} height={size} viewBox={`0 0 ${n} ${n}`}
         shapeRendering="crispEdges">
      <rect width={n} height={n} fill="#FFFFFF" />
      <path d={d} fill="#000000" />
    </svg>
  );
}
