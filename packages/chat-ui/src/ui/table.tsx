/**
 * The overviews' table (docs/design/sidebar.md §4): React Aria's Table. Arrow keys move between rows
 * and cells, Enter on a row runs its action (opening it); a cell's own buttons (a pin, a row's menu)
 * are reached with the arrow keys and Tab. A column can sort; the caller sorts the rows. 25 rows per
 * page with `Pager`; at that size the rows aren't virtualised (nothing would be gained).
 *
 * `FilterSelect`: a filter as a chip. Active (anything but its first option), it is drawn as
 * `surface-alt` with a darker border and has a clear button. `FilterToggle`: a chip that is on or off
 * ("Show closed"), drawn the same way when on. `PinToggle`: a row's pin (docs/design/sidebar.md §3).
 */
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Pin, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  Button as AriaButton,
  Cell,
  Column,
  Row,
  Table,
  TableBody,
  TableHeader,
  ToggleButton,
  type SortDescriptor,
} from "react-aria-components";
import { cx } from "./Button";
import { Select, type Option } from "./menus";

export type TableColumn<T> = {
  id: string;
  label: string;
  /** The label is for screen readers only (a pin column, the row menus). */
  hideLabel?: boolean;
  /** The cell that names the row for a screen reader. Exactly one column. */
  rowHeader?: boolean;
  allowsSorting?: boolean;
  /** "end" for numbers. */
  align?: "end";
  /** A CSS width ("44px", "minmax(...)" isn't supported: give px or %). */
  width?: string;
  render: (row: T) => ReactNode;
};

export function DataTable<T extends { id: string }>({ label, columns, rows, onRowAction, sort, onSortChange, empty, className }: {
  label: string;
  columns: TableColumn<T>[];
  rows: T[];
  /** Enter or a click on the row (outside its own buttons): open it. */
  onRowAction?: (row: T) => void;
  sort?: SortDescriptor;
  onSortChange?: (sort: SortDescriptor) => void;
  /** What the body says when there are no rows. */
  empty?: string;
  className?: string;
}) {
  const byId = new Map(rows.map((r) => [r.id, r]));
  return (
    <div className={cx("ui-table-wrap", className)}>
      <Table aria-label={label} className="ui-table" sortDescriptor={sort} onSortChange={onSortChange}
             onRowAction={onRowAction ? (key) => { const r = byId.get(String(key)); if (r) onRowAction(r); } : undefined}>
        <TableHeader className="ui-table-head">
          {columns.map((c) => (
            <Column key={c.id} id={c.id} isRowHeader={c.rowHeader} allowsSorting={c.allowsSorting} textValue={c.label}
                    className="ui-table-column" data-align={c.align} style={c.width ? { width: c.width } : undefined}>
              {({ sortDirection, allowsSorting }) => (
                <span className="ui-table-column-label">
                  <span className={c.hideLabel ? "ui-visually-hidden" : undefined}>{c.label}</span>
                  {allowsSorting && sortDirection && (sortDirection === "ascending"
                    ? <ChevronUp size={12} aria-hidden /> : <ChevronDown size={12} aria-hidden />)}
                </span>
              )}
            </Column>
          ))}
        </TableHeader>
        <TableBody className="ui-table-body" items={rows} renderEmptyState={() => <p className="ui-table-empty">{empty}</p>}>
          {(row) => (
            <Row id={row.id} className="ui-table-row" columns={columns}>
              {(c) => <Cell className="ui-table-cell" data-align={c.align}>{c.render(row)}</Cell>}
            </Row>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

/** "1–25 of 412" with Previous and Next. */
export function Pager({ page, size, total, onPage, text }: {
  page: number; size: number; total: number; onPage: (page: number) => void;
  text: { range: (from: number, to: number, total: number) => string; previous: string; next: string };
}) {
  if (total <= size) return null;
  const from = page * size + 1;
  const to = Math.min(total, from + size - 1);
  return (
    <nav className="ui-pager" aria-label={text.range(from, to, total)}>
      <span className="ui-pager-range" aria-live="polite">{text.range(from, to, total)}</span>
      <AriaButton className="ui-pager-button" isDisabled={page === 0} onPress={() => onPage(page - 1)}>
        <ChevronLeft size={14} aria-hidden /> {text.previous}
      </AriaButton>
      <AriaButton className="ui-pager-button" isDisabled={to >= total} onPress={() => onPage(page + 1)}>
        {text.next} <ChevronRight size={14} aria-hidden />
      </AriaButton>
    </nav>
  );
}

/** A filter chip: a Select whose first option means "all"; active, it shows a clear button. */
export function FilterSelect({ label, options, value, onChange, icon, clearLabel }: {
  label: string; options: Option[]; value: string; onChange: (id: string) => void; icon?: ReactNode; clearLabel: string;
}) {
  const active = value !== options[0]?.id;
  return (
    <span className="ui-filter" data-active={active || undefined}>
      <Select label={label} options={options} value={value} onChange={onChange} icon={icon} className="ui-filter-select" />
      {active && (
        <AriaButton className="ui-filter-clear" aria-label={clearLabel} onPress={() => onChange(options[0].id)}>
          <X size={12} aria-hidden />
        </AriaButton>
      )}
    </span>
  );
}

/** A chip that is on or off; on, it looks like an active filter and shows a ×. */
export function FilterToggle({ children, isSelected, onChange, icon }: {
  children: ReactNode; isSelected: boolean; onChange: (on: boolean) => void; icon?: ReactNode;
}) {
  return (
    <ToggleButton className="ui-filter ui-filter-toggle" isSelected={isSelected} onChange={onChange} data-active={isSelected || undefined}>
      {icon && <span className="ui-filter-icon" aria-hidden>{icon}</span>}
      {children}
      {isSelected && <X size={12} aria-hidden className="ui-filter-toggle-x" />}
    </ToggleButton>
  );
}

/** A row's pin: pressed when pinned. `label` names what it pins ("Pin case 123"). */
export function PinToggle({ label, isSelected, onChange }: { label: string; isSelected: boolean; onChange: (on: boolean) => void }) {
  return (
    <ToggleButton className="ui-pin" aria-label={label} isSelected={isSelected} onChange={onChange}>
      <Pin size={14} aria-hidden />
    </ToggleButton>
  );
}

export type { SortDescriptor };
