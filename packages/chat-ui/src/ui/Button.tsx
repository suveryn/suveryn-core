/**
 * Buttons (suveryn-tracker#44). React Aria's Button: Enter and Space, touch and mouse behave the same,
 * and focus shows only for the keyboard. Styled in ui.css through its data-* states
 * ([data-hovered], [data-pressed], [data-focus-visible], [data-disabled]) and data-variant.
 */
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from "react-aria-components";

export type ButtonProps = Omit<AriaButtonProps, "className" | "children"> & {
  /** primary: the one main action on a screen (accent fill). secondary: outlined. quiet: no border.
   *  plain: React Aria's behaviour with no look of its own, for a screen's own pieces (a citation
   *  marker, a chip); `className` gives the look. */
  variant?: "primary" | "secondary" | "quiet" | "plain";
  className?: string;
  children?: ReactNode;
  title?: string;
};

export function Button({ variant = "secondary", className, title, ...props }: ButtonProps) {
  const ref = useTitle(title);
  if (variant === "plain") return <AriaButton {...props} ref={ref} className={className} />;
  return <AriaButton {...props} ref={ref} data-variant={variant} className={cx("ui-button", className)} />;
}

/** React Aria's Button doesn't pass `title` on, so the tooltip is set on the element itself. */
function useTitle(title: string | undefined) {
  const ref = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (!ref.current) return;
    if (title) ref.current.title = title;
    else ref.current.removeAttribute("title");
  }, [title]);
  return ref;
}

/** A button that reads as a text link: Cancel, Keep, Sign out. `danger` for the destructive one of a
 *  pair (bold; the brand has no red). */
export function TextButton({ danger, className, title, ...props }: Omit<ButtonProps, "variant"> & { danger?: boolean }) {
  const ref = useTitle(title);
  return <AriaButton {...props} ref={ref} className={cx("ui-text-button", className)} data-danger={danger || undefined} />;
}

/** A button with only an icon. `label` is its name for screen readers and its tooltip. */
export function IconButton({ label, size = "normal", className, ...props }:
  Omit<ButtonProps, "variant" | "title" | "aria-label"> & { label: string; size?: "normal" | "small" }) {
  const ref = useTitle(label);
  return <AriaButton {...props} ref={ref} aria-label={label} className={cx("ui-icon-button", className)}
                     data-size={size === "small" ? "small" : undefined} />;
}

/** Class names joined, the empty ones left out. */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}
