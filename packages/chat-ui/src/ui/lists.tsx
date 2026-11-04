/**
 * Lists and look-ups on React Aria (suveryn-tracker#44), added for cases (suveryn-tracker#10):
 *
 * - ComboBoxField: a text field with suggestions, for a value that is usually one of a short list
 *   but may be the user's own (a case type: the notarial list, or another sector's word). Typing
 *   filters the suggestions; arrow keys move, Enter chooses, Escape closes; a typed value stays.
 *   Suggestions that arrive after the last keystroke (a directory searched as you type) open the
 *   list too: React Aria opens it only on a keystroke, with the suggestions in hand at that moment.
 * - SearchField: a search box with a clear button (Escape clears too), to filter a list.
 */
import { Check, ChevronDown, CircleAlert, Search, X } from "lucide-react";
import { useContext, useEffect, useRef } from "react";
import {
  Button as AriaButton,
  ComboBox,
  ComboBoxStateContext,
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
      <OpenOnLateSuggestions options={options} />
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

/** Whether new suggestions should open the list: they are new, the person is in the field and has typed
 *  something they haven't chosen yet, and the list is closed. (Whether any suggestion matches what was
 *  typed, React Aria decides when asked to open.) */
export function opensOnArrival(s: { before: string; after: string; focused: boolean; open: boolean; typed: string; chosen: boolean }): boolean {
  return s.after !== s.before && s.after !== "" && s.focused && !s.open && s.typed.trim() !== "" && !s.chosen;
}

/** Opens the list when the suggestions change after the last keystroke (the member search's directory
 *  answering ~300 ms later; found by the end-to-end walk-through). */
function OpenOnLateSuggestions({ options }: { options: Option[] }) {
  const state = useContext(ComboBoxStateContext);
  const ids = options.map((o) => o.id).join("\n");
  const before = useRef(ids);
  useEffect(() => {
    const was = before.current;
    before.current = ids;
    if (state && opensOnArrival({ before: was, after: ids, focused: state.isFocused, open: state.isOpen,
                                  typed: state.inputValue, chosen: state.selectedKey != null })) state.open(null, "input");
  }, [ids, state]);
  return null;
}

export function SearchField({ label, value, onChange, placeholder, className, autoFocus }: {
  /** The accessible name ("Find a case"); shown as the placeholder when none is given. */
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; className?: string;
  /** The field takes the focus when it appears (a search view opened for it). */
  autoFocus?: boolean;
}) {
  return (
    <AriaSearchField aria-label={label} value={value} onChange={onChange} className={cx("ui-search", className)}>
      <Search size={14} aria-hidden className="ui-search-icon" />
      <Input className="ui-search-input" placeholder={placeholder ?? label} autoFocus={autoFocus} />
      <AriaButton className="ui-search-clear"><X size={14} aria-hidden /></AriaButton>
    </AriaSearchField>
  );
}
