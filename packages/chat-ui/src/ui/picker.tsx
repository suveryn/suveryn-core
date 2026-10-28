/**
 * DocumentPicker (docs/design/chat-ui.md §10, artboards 17 to 19): a button that opens a choice of
 * documents, several at once, with search. `MenuButton` can't do multiple choice with search, so this
 * is a `DialogTrigger` with a `Popover` (on a narrow screen a sheet from the bottom, with *Done*):
 *
 * - first an "everything" option, chosen when nothing else is;
 * - a `SearchField` once there are `searchFrom` items or more;
 * - a `ListBox` with `selectionMode="multiple"`: the chosen items first, under their own heading, even
 *   when the search no longer matches them; then the others (matching the search);
 * - an action at the bottom (upload a new one) and a line of fine print.
 *
 * Keyboard: Enter, Space or arrow down on the button opens; typing in the search field searches;
 * Space chooses in the list; Escape closes and keeps the choice. The button's name says what is chosen.
 */
import { Check, Upload } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Button as AriaButton,
  Dialog as AriaDialog,
  DialogTrigger,
  Header,
  ListBox,
  ListBoxItem,
  ListBoxSection,
  Modal,
  ModalOverlay,
  Popover,
  Text,
  type Selection,
} from "react-aria-components";
import { cx } from "./Button";
import { SearchField } from "./lists";

export type PickItem = { id: string; label: string; meta?: string };

export function DocumentPicker({ items, selected, onChange, trigger, triggerLabel, label, allLabel, allMeta, chosenHeading,
                                 othersHeading, searchLabel, searchFrom = 9, action, footnote, narrow = false, doneLabel,
                                 className }: {
  items: PickItem[];
  /** The chosen ids; none: everything. */
  selected: string[];
  onChange: (ids: string[]) => void;
  /** The button's content, and its accessible name ("Ask about, 2 documents chosen"). */
  trigger: ReactNode;
  triggerLabel: string;
  /** The dialog's name ("Ask about"). */
  label: string;
  allLabel: string;
  allMeta?: string;
  /** "Chosen · 2"; the others' heading, from the search ("Matching 'akte' · 2") or null for none. */
  chosenHeading: (n: number) => string;
  othersHeading: (query: string, n: number) => string | null;
  searchLabel: string;
  searchFrom?: number;
  /** An action under the list (upload a new document): it closes the picker first. */
  action?: { label: string; description?: string; onPress: () => void };
  footnote?: string;
  /** A sheet from the bottom instead of a popover, with *Done*. */
  narrow?: boolean;
  doneLabel: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const chosen = new Set(selected);
  const q = query.trim().toLocaleLowerCase();
  const matches = (i: PickItem) => !q || i.label.toLocaleLowerCase().includes(q);
  const first = items.filter((i) => chosen.has(i.id));
  const rest = items.filter((i) => !chosen.has(i.id) && matches(i));
  const restHeading = othersHeading(query.trim(), rest.length);
  const onSelection = (keys: Selection) => {
    const ids = keys === "all" ? items.map((i) => i.id) : [...keys].map(String);
    onChange(items.map((i) => i.id).filter((id) => ids.includes(id)));  // in the list's order
  };
  const close = () => { setOpen(false); setQuery(""); };
  const onKey = (e: KeyboardEvent) => { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } };

  const row = (i: PickItem) => (
    <ListBoxItem key={i.id} id={i.id} textValue={i.label} className="ui-pick-option">
      {({ isSelected }) => (
        <>
          <span className="ui-pick-box" data-on={isSelected || undefined} aria-hidden>{isSelected && <Check size={12} strokeWidth={3} />}</span>
          <span className="ui-pick-text">
            <Text slot="label" className="ui-pick-label">{i.label}</Text>
            {i.meta && <Text slot="description" className="ui-pick-meta">{i.meta}</Text>}
          </span>
        </>
      )}
    </ListBoxItem>
  );
  const body = (
    <AriaDialog aria-label={label} className="ui-pick-dialog">
      <AriaButton className="ui-pick-all" aria-pressed={selected.length === 0} onPress={() => onChange([])}>
        <span className="ui-pick-radio" data-on={selected.length === 0 || undefined} aria-hidden />
        <span className="ui-pick-text"><span className="ui-pick-label">{allLabel}</span>
          {allMeta && <span className="ui-pick-meta">{allMeta}</span>}</span>
      </AriaButton>
      <div className="ui-pick-rule" />
      {items.length >= searchFrom && <SearchField label={searchLabel} value={query} onChange={setQuery} className="ui-pick-search" />}
      <ListBox aria-label={label} selectionMode="multiple" selectedKeys={selected} onSelectionChange={onSelection} escapeKeyBehavior="none"
               className="ui-pick-list" renderEmptyState={() => null}>
        {first.length > 0 && (
          <ListBoxSection>
            <Header className="ui-pick-heading">{chosenHeading(first.length)}</Header>
            {first.map(row)}
          </ListBoxSection>
        )}
        {rest.length > 0 && (
          <ListBoxSection>
            {restHeading && <Header className="ui-pick-heading">{restHeading}</Header>}
            {rest.map(row)}
          </ListBoxSection>
        )}
      </ListBox>
      {action && <>
        <div className="ui-pick-rule" />
        <AriaButton className="ui-pick-all" onPress={() => { close(); action.onPress(); }}>
          <Upload size={14} aria-hidden className="ui-pick-icon" />
          <span className="ui-pick-text"><span className="ui-pick-label">{action.label}</span>
            {action.description && <span className="ui-pick-meta">{action.description}</span>}</span>
        </AriaButton>
      </>}
      {footnote && <p className="ui-pick-fine">{footnote}</p>}
      {narrow && <AriaButton className="ui-button ui-pick-done" data-variant="primary" onPress={close}>{doneLabel}</AriaButton>}
    </AriaDialog>
  );
  return (
    <DialogTrigger isOpen={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <AriaButton className={cx("ui-pick-trigger", className)} aria-label={triggerLabel} onKeyDown={onKey}>{trigger}</AriaButton>
      {narrow
        ? <ModalOverlay isDismissable className="ui-sheet-overlay"><Modal className="ui-sheet">{body}</Modal></ModalOverlay>
        : <Popover className="ui-popover ui-pick-popover" placement="top start" offset={8}>{body}</Popover>}
    </DialogTrigger>
  );
}
