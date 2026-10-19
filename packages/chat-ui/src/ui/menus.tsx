/**
 * Lists that open from a button (suveryn-tracker#44), on React Aria:
 *
 * - Select: one value from a short list (the language menu). A button showing the value opens a
 *   listbox; arrow keys, Home/End and typing a letter move, Enter chooses, Escape closes, and the
 *   focus returns to the button.
 * - MenuButton: a menu of choices that act at once (the chat's model menu). With `selected`, its items
 *   are single-choice (menuitemradio) and the chosen one is ticked.
 * - ActionMenu: a richer menu (the sidebar's account menu, a case's actions; docs/design/sidebar.md):
 *   items with an icon and a meta text, separators, an item that opens a submenu (the language), a
 *   header above the items and fine print under them. The trigger is any content; the button is
 *   the menu's own, so the look of the trigger belongs to the caller's class.
 *
 * Both open in a Popover, positioned by React Aria with style properties set through the DOM, which
 * the appliance's CSP allows (it blocks only <style> elements and style attributes in markup).
 */
import { Check, ChevronDown, ChevronRight, CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import {
  Button as AriaButton,
  FieldError,
  Label,
  ListBox,
  ListBoxItem,
  Menu,
  Header,
  MenuItem,
  MenuSection,
  MenuTrigger,
  Popover,
  Select as AriaSelect,
  SelectValue,
  Separator,
  SubmenuTrigger,
  Text,
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

/** A select with a visible label and an optional hint, for forms (the backup disk, the retention). */
export function SelectField({ name, label, description, options, value, onChange, size }: {
  name: string; label: string; description?: string; options: Option[]; value: string; onChange: (id: string) => void;
  /** As the text fields (fields.tsx, FieldSize). */
  size?: "regular" | "small";
}) {
  return (
    <AriaSelect name={name} selectedKey={value} onSelectionChange={(k) => k != null && onChange(String(k))}
                className="ui-field ui-select-field" data-size={size === "small" ? "small" : undefined}>
      <Label className="ui-label">{label}</Label>
      <AriaButton className="ui-input ui-select-field-button">
        <SelectValue className="ui-select-value" />
        <ChevronDown size={16} aria-hidden />
      </AriaButton>
      {description && <Text slot="description" className="ui-hint">{description}</Text>}
      <FieldError className="ui-field-error">
        {({ validationErrors }) => <><CircleAlert size={16} aria-hidden /><span>{validationErrors.join(" ")}</span></>}
      </FieldError>
      <Popover className="ui-popover" placement="bottom start" offset={6}>
        <ListBox className="ui-listbox">
          {options.map((o) => (
            <ListBoxItem key={o.id} id={o.id} textValue={o.label} className="ui-option">
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
                  {/* label and description slots: read as the item's name, then its description */}
                  <Text slot="label" className="ui-menu-item-label">{i.label}</Text>
                  {i.description && <Text slot="description" className="ui-menu-item-desc">{i.description}</Text>}
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

/** One entry of an ActionMenu: an action, or `"-"` for a separator between groups. */
export type MenuEntry = "-" | { heading: string; items: MenuEntry[] } | {
  id: string;
  label: string;
  /** A small icon before the label (decorative). */
  icon?: ReactNode;
  /** A short text after the label, dimmed ("1.2K tokens today"). */
  meta?: string;
  /** teal: a good sign ("Covered"); warn: a warning that never blocks ("Not covered"). */
  metaTone?: "teal" | "warn";
  /** A small icon before the meta (decorative). */
  metaIcon?: ReactNode;
  /** A second line under the label. */
  description?: string;
  /** accent: for an action that stands out (an administrator's playbooks). */
  tone?: "accent";
  /** Entries of a submenu this item opens; `selected` is the ticked one. */
  submenu?: MenuEntry[];
  selected?: string;
  isDisabled?: boolean;
};

type ActionMenuProps = {
  /** The trigger's content. */
  children: ReactNode;
  /** The trigger's accessible name (required when its content is an icon or an avatar). */
  "aria-label"?: string;
  /** The menu's name. */
  menuLabel: string;
  entries: MenuEntry[];
  onAction: (id: string) => void;
  /** Shown above the items (an account's name), inside the popover. */
  header?: ReactNode;
  /** Shown under the items (fine print). */
  footer?: ReactNode;
  placement?: Placement;
  /** The trigger's class (the look is the caller's). */
  className?: string;
  popoverClassName?: string;
  isDisabled?: boolean;
};

function entries(items: MenuEntry[], onAction: (id: string) => void) {
  return items.map((e, i) => {
    if (e === "-") return <Separator key={`sep-${i}`} className="ui-menu-separator" />;
    if ("heading" in e) {  // a group under a small label ("Administrators only")
      return (
        <MenuSection key={`section-${i}`} className="ui-menu-section">
          <Header className="ui-menu-section-title">{e.heading}</Header>
          {entries(e.items, onAction)}
        </MenuSection>
      );
    }
    const content = (selected?: boolean) => (
      <>
        {e.icon && <span className="ui-menu-item-icon" aria-hidden>{e.icon}</span>}
        <Text slot="label" className="ui-menu-item-label">{e.label}</Text>
        {e.description && <Text slot="description" className="ui-menu-item-desc-line">{e.description}</Text>}
        {e.meta && (e.description
          ? <span className="ui-menu-item-meta" data-tone={e.metaTone}>{e.metaIcon}{e.meta}</span>
          : <Text slot="description" className="ui-menu-item-meta" data-tone={e.metaTone}>{e.metaIcon}{e.meta}</Text>)}
        {e.submenu && <ChevronRight size={14} aria-hidden className="ui-menu-item-more" />}
        {selected && <Check size={14} aria-hidden className="ui-menu-item-check" />}
      </>
    );
    if (e.submenu) {
      return (
        <SubmenuTrigger key={e.id}>
          <MenuItem id={e.id} textValue={e.label} className="ui-menu-item ui-menu-item-rich" data-tone={e.tone} isDisabled={e.isDisabled}
                    data-described={e.description ? true : undefined}>
            {content()}
          </MenuItem>
          <Popover className="ui-popover ui-popover-sub" placement="end top" offset={-6}>
            <Menu aria-label={e.label} className="ui-menu"
                  selectionMode={e.selected === undefined ? undefined : "single"}
                  selectedKeys={e.selected === undefined ? undefined : [e.selected]}
                  onAction={(k: Key) => onAction(String(k))}>
              {entries(e.submenu, onAction)}
            </Menu>
          </Popover>
        </SubmenuTrigger>
      );
    }
    return (
      <MenuItem key={e.id} id={e.id} textValue={e.label} className="ui-menu-item ui-menu-item-rich" data-tone={e.tone} isDisabled={e.isDisabled}
                data-described={e.description ? true : undefined}>
        {({ isSelected }) => content(isSelected)}
      </MenuItem>
    );
  });
}

export function ActionMenu({ children, menuLabel, entries: items, onAction, header, footer, placement = "bottom start",
                             className, popoverClassName, isDisabled, ...rest }: ActionMenuProps) {
  return (
    <MenuTrigger>
      <AriaButton className={cx("ui-menu-trigger", className)} aria-label={rest["aria-label"]} isDisabled={isDisabled}>
        {children}
      </AriaButton>
      <Popover className={cx("ui-popover", "ui-popover-rich", popoverClassName)} placement={placement} offset={6}>
        {header && <div className="ui-menu-header">{header}</div>}
        <Menu aria-label={menuLabel} className="ui-menu" onAction={(k: Key) => onAction(String(k))}>
          {entries(items, onAction)}
        </Menu>
        {footer && <div className="ui-menu-footer">{footer}</div>}
      </Popover>
    </MenuTrigger>
  );
}
