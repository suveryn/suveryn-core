/**
 * Avatar: a person's picture, or their initials, in the rounded square of the brand mark's outer
 * boundary (corner radius a quarter of the side, as suveryn-icon.svg: rx 5 on 20) with a fine line
 * border. An administrator wears a shield over the corner, an overlay icon like any other
 * (IconBadge). The picture is the gateway's `/v1/users/{sub}/avatar`, keyed by its ETag so a new
 * upload shows at once; when there is none, or it fails to load, the initials show instead (never a
 * broken image).
 */
import { Shield } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cx } from "./Button";

export type AvatarSize = "small" | "normal" | "large" | "huge";  // 24, 32, 48, 96 px

/** What an overlay icon sits on: an icon or the brand mark (14 to 20 px), or an avatar of that size. */
export type BadgeHost = "icon" | AvatarSize;

/**
 * An overlay icon: a small icon over the corner of another, saying one thing about it (suveryn-brand
 * guidelines, "Overlay icons"). The administrator's shield on an avatar, the manager's folder, the
 * shared conversation's speech bubble, the route of a playbook speaking. `badge` is the icon; the
 * children are what it sits on, and `host` says which (its size sets the badge's). Decorative: the
 * meaning is in the parent's accessible name.
 */
export function IconBadge({ badge, children, className, host, tone }: {
  badge: ReactNode; children: ReactNode; className?: string;
  host: BadgeHost;
  /** system: the system signals something (teal-ink: a playbook speaking); role: a role or ownership (ink). */
  tone: "system" | "role";
}) {
  return (
    <span className={cx("ui-badged", className)}>
      {children}
      <span className="ui-badge" data-host={host} data-tone={tone} aria-hidden>{badge}</span>
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

export function Avatar({ name, sub, etag, admin, size = "normal", adminLabel, shield = true, className }: {
  name: string;
  sub?: string;
  /** The ETag of the person's picture (from the API); null or undefined: initials. */
  etag?: string | null;
  admin?: boolean;
  size?: AvatarSize;
  /** Text for the badge (screen readers): "Administrator". */
  adminLabel?: string;
  /** false where another badge sits on this avatar (IconBadge): one badge at a time (chat-ui.md); the
   * name still says "Administrator". */
  shield?: boolean;
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
      {admin && shield && <span className="ui-badge" data-host={size} data-tone="role" aria-hidden><Shield /></span>}
    </span>
  );
}
