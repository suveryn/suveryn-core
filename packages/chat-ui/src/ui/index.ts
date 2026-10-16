/**
 * sūveryn's component library (suveryn-tracker#44): React Aria Components for behaviour and
 * accessibility, styled with the brand tokens in ui.css. Product screens use only these, never React
 * Aria directly, so the look and behaviour stay the same everywhere. Used by the chat UI and the
 * appliance's web setup (src/setup), which shares nothing else with it.
 */
// Imported for its effect, first: keeps React Aria within the CSP (docs/content-security-policy.md).
// src/csp.test.ts checks this line.
import "./csp";
import "./ui.css";

export { CopyButton, LinkButton, Progress } from "./actions";
export { Button, cx, IconButton, TextButton, type ButtonProps } from "./Button";
export { Checkbox, RadioCards, RadioList, Segmented, type Choice } from "./choices";
export { DateField, NumberField, PasswordField, TextArea, TextField, type FieldSize } from "./fields";
export { Dialog } from "./dialog";
export { FileButton, FileDrop, FilePick, readText } from "./files";
export { Form, FormError, useFieldError, useFormPending, type FieldErrors } from "./forms";
export { Card, Chips, Facts, InlineNotice, Note, Notice, Rows, StatusList, Steps, type Fact, type Row, type Status, type StatusItem } from "./layout";
export { ComboBoxField, SearchField, SelectList, type ListEntry } from "./lists";
export { MenuButton, Select, SelectField, type Option } from "./menus";
export { QrCode } from "./QrCode";
export { I18nProvider } from "react-aria-components";
export { BarChart, ColumnChart, type ChartText, type Datum, type Series } from "./charts";
