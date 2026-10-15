/**
 * Buttons (suveryn-tracker#44). React Aria's Button: Enter and Space, touch and mouse behave the same,
 * and focus shows only for the keyboard. Styled in ui.css through its data-* states
 * ([data-hovered], [data-pressed], [data-focus-visible], [data-disabled]) and data-variant.
 */
import type { ReactNode } from "react";
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from "react-aria-components";

export type ButtonProps = Omit<AriaButtonProps, "className" | "children"> & {
  /** primary: the one main action on a screen (accent fill). secondary: outlined. quiet: no border. */
  variant?: "primary" | "secondary" | "quiet";
  className?: string;
  children?: ReactNode;
};

export function Button({ variant = "secondary", className, ...props }: ButtonProps) {
  return <AriaButton {...props} data-variant={variant} className={cx("ui-button", className)} />;
}

/** Class names joined, the empty ones left out. */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}
