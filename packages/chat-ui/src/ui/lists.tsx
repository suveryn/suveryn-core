/**
 * Lists and look-ups on React Aria (suveryn-tracker#44), added for cases (suveryn-tracker#10):
 *
 * - ComboBoxField: a text field with suggestions, for a value that is usually one of a short list
 *   but may be the user's own (a case type: the notarial list, or another sector's word). Typing
 *   filters the suggestions; arrow keys move, Enter chooses, Escape closes; a typed value stays.
 * - SearchField: a search box with a clear button (Escape clears too), to filter a list.
 * - SelectList: a list where one item is the current one (the cases in the sidebar). Arrow keys,
 *   Home/End and typing a letter move between items, Enter or a click opens one; the current item
 *   is `aria-selected`. Each item can render its own content.
 */
import { Check, ChevronDown, CircleAlert, Search, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  Button as AriaButton,
  ComboBox,
  FieldError,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  SearchField as AriaSearchField,
  Text,
} from "react-aria-components";
import { cx } from "./Button";
import type { Option } from "./menus";

export function ComboBoxField({ name, label, description, options, value, onChange, placeholder }: {
  name: string; label: string; description?: string; options: Option[]; value: string; onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <ComboBox name={name} allowsCustomValue inputValue={value} onInputChange={onChange}
              selectedKey={options.find((o) => o.label === value)?.id ?? null}
              onSelectionChange={(k) => { const o = options.find((x) => x.id === k); if (o) onChange(o.label); }}
              className="ui-field ui-combobox">
      <Label className="ui-label">{label}</Label>
      <div className="ui-input-group">
        <Input className="ui-input" placeholder={placeholder} />
        <AriaButton className="ui-icon-button ui-combobox-open" aria-label={label}><ChevronDown size={16} aria-hidden /></AriaButton>
      </div>
      {description && <Text slot="description" className="ui-hint">{description}</Text>}
      <FieldError className="ui-field-error">
        {({ validationErrors }) => <><CircleAlert size={16} aria-hidden /><span>{validationErrors.join(" ")}</span></>}
      </FieldError>
      <Popover className="ui-popover" placement="bottom start" offset={6}>
        <ListBox className="ui-listbox">
          {options.map((o) => (
            <ListBoxItem key={o.id} id={o.id} textValue={o.label} className="ui-option">
              {({ isSelected }) => <><span>{o.label}</span>{isSelected && <Check size={14} aria-hidden />}</>}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </ComboBox>
  );
}

export function SearchField({ label, value, onChange, placeholder, className }: {
  /** The accessible name ("Find a case"); shown as the placeholder when none is given. */
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; className?: string;
}) {
  return (
    <AriaSearchField aria-label={label} value={value} onChange={onChange} className={cx("ui-search", className)}>
      <Search size={14} aria-hidden className="ui-search-icon" />
      <Input className="ui-search-input" placeholder={placeholder ?? label} />
      <AriaButton className="ui-search-clear"><X size={14} aria-hidden /></AriaButton>
    </AriaSearchField>
  );
}

export type ListEntry = { id: string; textValue: string };

export function SelectList<T extends ListEntry>({ label, items, current, onOpen, children, className }: {
  /** The list's accessible name ("Cases"). */
  label: string;
  items: T[];
  /** The id of the current item, if any. */
  current: string | null;
  onOpen: (item: T) => void;
  /** Renders one item's content. */
  children: (item: T, isCurrent: boolean) => ReactNode;
  className?: string;
}) {
  return (
    <ListBox aria-label={label} items={items} selectionMode="single" selectionBehavior="replace"
             selectedKeys={current === null ? [] : [current]} disallowEmptySelection
             onSelectionChange={(keys) => {
               if (keys === "all") return;
               const [key] = keys;
               const item = items.find((i) => i.id === String(key));
               if (item) onOpen(item);
             }}
             className={cx("ui-select-list", className)}>
      {(item) => (
        <ListBoxItem id={item.id} textValue={item.textValue} className="ui-select-list-item">
          {({ isSelected }) => children(item, isSelected)}
        </ListBoxItem>
      )}
    </ListBox>
  );
}
