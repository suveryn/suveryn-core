/**
 * The Sūveryn mark in the UI: the header lockup and the assistant marker. The mark itself is
 * src/brand/suveryn-icon.svg, copied from suveryn-brand (not AGPL; see src/brand/README.md).
 * Brand rules: https://github.com/suveryn/suveryn-brand/blob/main/guidelines/brand-guidelines.md
 */
import icon from "../brand/suveryn-icon.svg";

/** Header lockup: 30px icon, 22px wordmark, 12px gap (the brand guidelines' fixed ratio). */
export function Lockup() {
  return (
    <div className="lockup">
      <img src={icon} width={30} height={30} alt="" />
      <span className="wordmark">sūveryn</span>
    </div>
  );
}

/**
 * Marks the assistant's turn instead of a message bubble: the brand mark's geometry as a teal
 * outline (brand guidelines: https://github.com/suveryn/suveryn-brand/blob/main/guidelines/brand-guidelines.md#a-named-interaction-pattern-no-assistant-bubble).
 */
export function AssistantMark() {
  return (
    <svg className="assistant-mark" width="20" height="20" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="20" height="20" rx="5" stroke="var(--teal)" strokeWidth="1.8" />
      <rect x="6.5" y="5.5" width="9" height="1.8" rx="0.9" fill="var(--teal)" />
      <rect x="8" y="9.8" width="6" height="6.7" rx="1.1" stroke="var(--teal)" strokeWidth="1.6" />
    </svg>
  );
}
