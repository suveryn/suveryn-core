/**
 * The avatar dialog (docs/design/avatars.md): pick a headshot, frame it, save. The picture is drawn
 * on a square canvas the size of the avatar's rounded square; the person drags it to move it and
 * uses the zoom slider to get closer. The frame never stretches the picture: it is scaled by one
 * factor in both directions ("cover" at zoom 1, so the frame is always filled), and panning is
 * clamped so no edge leaves the frame. Saving draws the same framing at 512 x 512 and sends the
 * PNG; the server re-encodes it. Everything happens in the browser until the save; nothing is
 * uploaded that the person hasn't seen.
 */
import { AlertCircle, ImagePlus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { removeMyAvatar, setMyAvatar, type Me } from "../api";
import { useT } from "../i18n";
import { Avatar, Button, Dialog, FileButton, InlineNotice, Slider, TextButton } from "../ui";

const FRAME = 240;      // CSS pixels of the editing canvas
const OUTPUT = 512;     // pixels of the square sent to the server
const MAX_ZOOM = 4;
const ACCEPT = ["image/png", "image/jpeg", "image/webp"];

type Framing = { zoom: number; x: number; y: number };  // x, y: the picture's offset from centred, in frame pixels

/** The drawing parameters for a frame of `side` pixels: the picture's drawn size and position. */
function placement(img: { width: number; height: number }, f: Framing, side: number) {
  const base = Math.max(side / img.width, side / img.height);  // cover
  const scale = base * f.zoom;
  const w = img.width * scale, h = img.height * scale;
  const k = side / FRAME;  // offsets were measured in the editing frame
  return { w, h, x: (side - w) / 2 + f.x * k, y: (side - h) / 2 + f.y * k };
}

/** Keeps the picture covering the whole frame: an offset can't expose an edge. */
function clamp(img: { width: number; height: number }, f: Framing): Framing {
  const { w, h } = placement(img, f, FRAME);
  const maxX = Math.max(0, (w - FRAME) / 2), maxY = Math.max(0, (h - FRAME) / 2);
  return { zoom: f.zoom, x: Math.min(maxX, Math.max(-maxX, f.x)), y: Math.min(maxY, Math.max(-maxY, f.y)) };
}

function draw(canvas: HTMLCanvasElement, img: HTMLImageElement, f: Framing) {
  const side = canvas.width;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, side, side);
  const p = placement(img, f, side);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, p.x, p.y, p.w, p.h);
}

export function AvatarDialog({ open, me, onClose, onChanged }: {
  open: boolean; me: Me; onClose: () => void; onChanged: (etag: string | null) => void;
}) {
  const m = useT();
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [framing, setFraming] = useState<Framing>({ zoom: 1, x: 0, y: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ startX: number; startY: number; x: number; y: number } | null>(null);
  const objectUrl = useRef<string | null>(null);

  const reset = useCallback(() => {
    setImg(null); setFraming({ zoom: 1, x: 0, y: 0 }); setError(null); setBusy(false);
    if (objectUrl.current) { URL.revokeObjectURL(objectUrl.current); objectUrl.current = null; }
  }, []);
  useEffect(() => { if (open) reset(); }, [open, reset]);
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, []);
  useEffect(() => { if (canvas.current && img) draw(canvas.current, img, framing); }, [img, framing]);

  const pick = (files: File[]) => {
    const file = files[0];
    if (!file) return;
    setError(null);
    if (!ACCEPT.includes(file.type)) { setError(m.avatarNotAPicture); return; }
    if (file.size > 20 * 1024 * 1024) { setError(m.avatarTooLarge); return; }
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = url;
      setFraming({ zoom: 1, x: 0, y: 0 });
      setImg(image);
    };
    image.onerror = () => { URL.revokeObjectURL(url); setError(m.avatarNotAPicture); };
    image.src = url;
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!img) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { startX: e.clientX, startY: e.clientY, x: framing.x, y: framing.y };
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!img || !drag.current) return;
    const d = drag.current;
    setFraming((f) => clamp(img, { ...f, x: d.x + (e.clientX - d.startX), y: d.y + (e.clientY - d.startY) }));
  };
  const onPointerUp = () => { drag.current = null; };
  const zoomTo = (zoom: number) => { if (img) setFraming((f) => clamp(img, { ...f, zoom })); };

  const save = async () => {
    if (!img) return;
    setBusy(true);
    setError(null);
    try {
      const out = document.createElement("canvas");
      out.width = out.height = OUTPUT;
      draw(out, img, framing);
      const blob = await new Promise<Blob | null>((resolve) => out.toBlob(resolve, "image/png"));
      if (!blob) throw new Error(m.avatarNotAPicture);
      const etag = await setMyAvatar(blob);
      onChanged(etag);
      onClose();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true);
    setError(null);
    try { await removeMyAvatar(); onChanged(null); onClose(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <Dialog isOpen={open} onClose={onClose} title={m.avatarTitle} busy={busy} actions={
      <>
        {img && <Button variant="primary" onPress={save} isDisabled={busy}>{busy ? m.saving : m.avatarSave}</Button>}
        {!img && me.avatar && <Button onPress={remove} isDisabled={busy}><Trash2 size={14} aria-hidden /> {m.avatarRemove}</Button>}
        <TextButton onPress={onClose}>{m.cancel}</TextButton>
      </>
    }>
      <p>{m.avatarIntro}</p>
      {img ? (
        <div className="avatar-editor">
          <canvas ref={canvas} className="avatar-frame" width={FRAME * 2} height={FRAME * 2}
                  onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
                  aria-label={m.avatarFrameLabel} role="img" />
          <Slider label={m.avatarZoom} value={framing.zoom} onChange={zoomTo} min={1} max={MAX_ZOOM} step={0.05}
                  format={(v) => `${v.toFixed(2)}×`} />
          <p className="caption">{m.avatarFrameHint}</p>
          <FileButton accept={ACCEPT} onSelect={pick}><TextButton>{m.avatarAnotherPicture}</TextButton></FileButton>
        </div>
      ) : (
        <div className="avatar-pick">
          <Avatar name={me.name} sub={me.sub} etag={me.avatar} admin={me.admin} size="huge" adminLabel={m.administrator} />
          <FileButton accept={ACCEPT} onSelect={pick}>
            <Button><ImagePlus size={16} aria-hidden /> {me.avatar ? m.avatarChoosePictureAgain : m.avatarChoosePicture}</Button>
          </FileButton>
          <p className="caption">{m.avatarPickHint}</p>
        </div>
      )}
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
