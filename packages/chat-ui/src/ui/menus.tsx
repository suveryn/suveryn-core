/**
 * Lists that open from a button (suveryn-tracker#44), on React Aria:
 *
 * - Select: one value from a short list (the language menu). A button showing the value opens a
 *   listbox; arrow keys, Home/End and typing a letter move, Enter chooses, Escape closes, and the
 *   focus returns to the button.
 * - MenuButton: a menu of choices that act at once (the chat's model menu). With `selected`, its items
 *   are single-choice (menuitemradio) and the chosen one is ticked.
 *
 * Both open in a Popover, positioned by React Aria with style properties set through the DOM, which
 * the appliance's CSP allows (it blocks only <style> elements and style attributes in markup).
 */
import { Check, ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import {
  Button as AriaButton,
  ListBox,
  ListBoxItem,
  Menu,
  MenuItem,
  MenuTrigger,
  Popover,
  Select as AriaSelect,
  SelectValue,
  type Key,
  type Placement,
} from "react-aria-components";
import { cx } from "./Button";

export type Option = { id: string; label: string; lang?: string; description?: string };

type SelectProps = {
  /** The name a screen reader announces ("Language"). */
  label: string;
  options: Option[];
  value: string;
  onChange: (id: string) => void;
  /** An icon shown before the button (decorative). */
  icon?: ReactNode;
  className?: string;
};

export function Select({ label, options, value, onChange, icon, className }: SelectProps) {
  return (
    <AriaSelect aria-label={label} selectedKey={value} onSelectionChange={(k) => k != null && onChange(String(k))}
                className={cx("ui-select", className)}>
      {icon && <span className="ui-select-icon" aria-hidden>{icon}</span>}
      <AriaButton className="ui-select-button">
        <SelectValue className="ui-select-value" />
        <ChevronDown size={14} aria-hidden />
      </AriaButton>
      <Popover className="ui-popover" placement="bottom end" offset={6}>
        <ListBox className="ui-listbox">
          {options.map((o) => (
            <ListBoxItem key={o.id} id={o.id} textValue={o.label} lang={o.lang} className="ui-option">
              {({ isSelected }) => (
                <>
                  <span>{o.label}</span>
                  {isSelected && <Check size={14} aria-hidden />}
                </>
              )}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}

type MenuButtonProps = {
  /** The button's content (it has a chevron after it). */
  children: ReactNode;
  /** The button's accessible name, when its content doesn't say enough. */
  "aria-label"?: string;
  /** The menu's name ("Model"). */
  menuLabel: string;
  items: Option[];
  /** Single choice: the chosen item's id. */
  selected?: string;
  onAction: (id: string) => void;
  placement?: Placement;
  className?: string;
  /** A class for the menu's popover (it is rendered at the end of the page, not inside the button). */
  popoverClassName?: string;
};

export function MenuButton({ children, menuLabel, items, selected, onAction, placement = "bottom start", className,
                             popoverClassName, ...rest }: MenuButtonProps) {
  return (
    <MenuTrigger>
      <AriaButton className={cx("ui-menu-button", className)} aria-label={rest["aria-label"]}>
        {children}
        <ChevronDown size={12} aria-hidden />
      </AriaButton>
      <Popover className={cx("ui-popover", popoverClassName)} placement={placement} offset={6}>
        <Menu aria-label={menuLabel} className="ui-menu"
              selectionMode={selected === undefined ? undefined : "single"}
              selectedKeys={selected === undefined ? undefined : [selected]}
              onAction={(k: Key) => onAction(String(k))}>
          {items.map((i) => (
            <MenuItem key={i.id} id={i.id} textValue={i.label} className="ui-menu-item">
              {({ isSelected }) => (
                <>
                  <span className="ui-menu-item-label">{i.label}</span>
                  {i.description && <span className="ui-menu-item-desc">{i.description}</span>}
                  {isSelected && <Check size={14} aria-hidden className="ui-menu-item-check" />}
                </>
              )}
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
