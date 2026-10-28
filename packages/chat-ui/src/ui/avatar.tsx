/**
 * Avatar: a person's picture, or their initials, in the rounded square of the brand mark's outer
 * boundary (corner radius a quarter of the side, as suveryn-icon.svg: rx 5 on 20) with a teal
 * border. An administrator wears a small shield badge over the corner. The picture is the
 * gateway's `/v1/users/{sub}/avatar`, keyed by its ETag so a new upload shows at once; when there
 * is none, or it fails to load, the initials show instead (never a broken image).
 */
import { Shield } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cx } from "./Button";

export type AvatarSize = "small" | "normal" | "large" | "huge";  // 24, 32, 48, 96 px

/**
 * A small badge over the corner of an icon or a picture: the administrator's shield on an avatar,
 * the link on a conversation that is in a case (docs/design/chat-ui.md). `badge` is the small icon;
 * the children are what it sits on. Decorative: the meaning is in the parent's accessible name.
 */
export function IconBadge({ badge, children, className, tone = "teal" }: {
  badge: ReactNode; children: ReactNode; className?: string;
  /** teal: a system-level signal (in a case); accent: a person's standing (the administrator's shield). */
  tone?: "teal" | "accent" | "neutral";
}) {
  return (
    <span className={cx("ui-badged", className)}>
      {children}
      <span className="ui-badge" data-tone={tone} aria-hidden>{badge}</span>
    </span>
  );
}

/** Up to two initials from a display name: the first letters of its first and last word. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter((w) => /\p{L}/u.test(w));
  if (words.length === 0) return "?";
  const first = [...words[0]].find((c) => /\p{L}/u.test(c)) ?? "";
  const last = words.length > 1 ? [...words[words.length - 1]].find((c) => /\p{L}/u.test(c)) ?? "" : "";
  return (first + last).toLocaleUpperCase();
}

/** The picture's URL for a person, or null without one (`etag` null or undefined). */
export function avatarUrl(sub: string, etag: string | null | undefined): string | null {
  return etag ? `/v1/users/${encodeURIComponent(sub)}/avatar?v=${encodeURIComponent(etag)}` : null;
}

export function Avatar({ name, sub, etag, admin, size = "normal", adminLabel, className }: {
  name: string;
  sub?: string;
  /** The ETag of the person's picture (from the API); null or undefined: initials. */
  etag?: string | null;
  admin?: boolean;
  size?: AvatarSize;
  /** Text for the badge (screen readers): "Administrator". */
  adminLabel?: string;
  className?: string;
}) {
  const url = sub ? avatarUrl(sub, etag) : null;
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [url]);
  const showPicture = url !== null && !failed;
  return (
    <span className={cx("ui-avatar", className)} data-size={size} role="img" aria-label={name + (admin && adminLabel ? `, ${adminLabel}` : "")}>
      <span className="ui-avatar-face">
        {showPicture
          ? <img className="ui-avatar-picture" src={url} alt="" draggable={false} onError={() => setFailed(true)} />
          : <span className="ui-avatar-initials" aria-hidden>{initialsOf(name)}</span>}
      </span>
      {admin && <span className="ui-badge ui-avatar-badge" data-tone="accent" aria-hidden><Shield /></span>}
    </span>
  );
}
