/**
 * Choosing files (suveryn-tracker#37, #44): React Aria's FileTrigger, a button that opens the file
 * picker. FileDrop also takes a file dragged onto it with the mouse; keyboard and screen-reader users
 * use its button, the one tab stop. (React Aria's DropZone adds a second, hidden tab stop named
 * "DropZone", in English, for keyboard drag and drop; plain drag events avoid that.)
 *
 * - FilePick: one row per file: a title, the accepted kinds, the chosen file's name, and an error.
 * - FileDrop: an area to drop a file onto, or choose one.
 * - FileButton: any button of the library opening the file picker (the chat's paperclip).
 */
import { CircleAlert, FileUp } from "lucide-react";
import type { ReactNode } from "react";
import { useId, useState } from "react";
import { Button as AriaButton, FileTrigger } from "react-aria-components";
import { cx } from "./Button";
import { useFieldError } from "./forms";

type FilePickProps = {
  /** The field's name in the form (its error comes from there). */
  name: string;
  title: string;
  /** The kinds of file, as shown (".crt or .pem"). */
  hint: string;
  accept: string[];
  file: File | null;
  onChange: (file: File | null) => void;
  chooseLabel: string;
  icon?: ReactNode;
};

export function FilePick({ name, title, hint, accept, file, onChange, chooseLabel, icon }: FilePickProps) {
  const id = useId();
  const { error, clear } = useFieldError(name);
  return (
    <div className="ui-file" data-invalid={error ? true : undefined} data-field-invalid={error ? true : undefined}>
      {icon && <span className="ui-file-icon" aria-hidden>{icon}</span>}
      <span className="ui-file-body">
        <span id={`${id}-title`} className="ui-file-title">{title}</span>
        <span id={`${id}-hint`} className="ui-file-hint">{file ? file.name : hint}</span>
      </span>
      <FileTrigger acceptedFileTypes={accept} onSelect={(files) => { const f = files?.[0] ?? null; if (f) { clear(); onChange(f); } }}>
        <AriaButton className="ui-button" data-size="small" data-variant="secondary"
                    aria-labelledby={`${id}-choose ${id}-title`}
                    aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}>
          <span id={`${id}-choose`}>{chooseLabel}</span>
        </AriaButton>
      </FileTrigger>
      {error && (
        <span id={`${id}-error`} className="ui-field-error ui-file-error">
          <CircleAlert size={16} aria-hidden />
          <span>{error}</span>
        </span>
      )}
    </div>
  );
}

type FileDropProps = {
  name: string;
  accept: string[];
  /** What dropping does, then the button: "Drop the manifest here, or" + "choose a file". */
  dropLabel: string;
  chooseLabel: string;
  /** Lines under it (what kind of file, where it is checked). */
  hints: string[];
  onFile: (file: File) => void;
};

export function FileDrop({ name, accept, dropLabel, chooseLabel, hints, onFile }: FileDropProps) {
  const id = useId();
  const { error, clear } = useFieldError(name);
  const [over, setOver] = useState(false);
  const take = (file: File | undefined) => { if (file) { clear(); onFile(file); } };
  return (
    <div className="ui-drop-wrap" data-field-invalid={error ? true : undefined}>
      <div
        className={cx("ui-drop", over && "ui-drop-target")}
        onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files[0]); }}
      >
        <span className="ui-drop-icon" aria-hidden><FileUp size={18} /></span>
        <p className="ui-drop-label">
          <span aria-hidden>{dropLabel}</span>{" "}
          <FileTrigger acceptedFileTypes={accept} onSelect={(files) => take(files?.[0] ?? undefined)}>
            <AriaButton className="ui-link-button" aria-describedby={`${id}-hints${error ? ` ${id}-error` : ""}`}>{chooseLabel}</AriaButton>
          </FileTrigger>
        </p>
        <span id={`${id}-hints`} className="ui-drop-hints">
          {hints.map((h) => <span key={h}>{h}</span>)}
        </span>
      </div>
      {error && (
        <span id={`${id}-error`} className="ui-field-error">
          <CircleAlert size={16} aria-hidden />
          <span>{error}</span>
        </span>
      )}
    </div>
  );
}

/** A file's text, refusing anything larger than `max` bytes (certificates and keys are small). */
export async function readText(file: File, max = 64 * 1024): Promise<string | null> {
  if (file.size > max) return null;
  return file.text();
}

/** Makes its one child, a button from this library, open the file picker. */
export function FileButton({ accept, multiple, onSelect, children }: {
  accept: string[]; multiple?: boolean; onSelect: (files: File[]) => void; children: ReactNode;
}) {
  return (
    <FileTrigger acceptedFileTypes={accept} allowsMultiple={multiple} onSelect={(files) => files && onSelect(Array.from(files))}>
      {children}
    </FileTrigger>
  );
}
