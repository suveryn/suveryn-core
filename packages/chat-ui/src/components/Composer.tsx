/**
 * The question box: text, the paperclip for PDFs, attachment chips and the model picker. Sending is
 * disabled while the model is unavailable or an attachment is still being read; Enter sends,
 * Shift+Enter starts a new line.
 */
import { ArrowUp, Paperclip } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import type { ModelInfo } from "../api";
import type { Attachment } from "../types";
import { isPending } from "../types";
import { AttachmentChip } from "./Chips";
import { loadingNote, ModelPicker } from "./ModelPicker";

type Props = {
  attachments: Attachment[];
  models: ModelInfo[];            // installed models (GET /v1/models)
  chosenModel: string | null;     // null: the default model
  onChooseModel: (id: string) => void;
  disabledReason: string | null; // why sending is impossible right now, shown under the input
  busy: boolean;                 // an answer is being written
  onAttach: (files: File[]) => void;
  onRemoveAttachment: (key: string) => void;
  onSend: (text: string) => void;
};

export function Composer({ attachments, models, chosenModel, onChooseModel, disabledReason, busy, onAttach,
                          onRemoveAttachment, onSend }: Props) {
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const waiting = attachments.some(isPending);
  const reason = disabledReason ?? (waiting ? "Waiting for your documents to be read…" : null);
  const note = loadingNote(models, chosenModel);
  const canSend = !reason && !busy && text.trim().length > 0;

  const send = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="composer-wrap">
      {attachments.length > 0 && (
        <div className="attachments pending">
          {attachments.map((a) => <AttachmentChip key={a.key} a={a} onRemove={() => onRemoveAttachment(a.key)} />)}
        </div>
      )}
      <div className="composer">
        <button type="button" className="icon-button" onClick={() => fileInput.current?.click()}
                aria-label="Attach a PDF" title="Attach a PDF">
          <Paperclip size={18} />
        </button>
        <input ref={fileInput} type="file" accept="application/pdf,.pdf" multiple hidden
               onChange={(e) => { onAttach(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        <label htmlFor="composer-input" className="visually-hidden">Your question</label>
        <textarea id="composer-input" rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
                  placeholder="Ask about your documents…" />
        <ModelPicker models={models} chosen={chosenModel} onChoose={onChooseModel} />
        <button type="button" className="send-button" onClick={send} disabled={!canSend} aria-label="Send message">
          <ArrowUp size={16} strokeWidth={2.2} />
        </button>
      </div>
      <p className="composer-hint caption" role="status">
        {reason ?? note ?? "Answers come from the documents in this conversation and cite the page they come from."}
      </p>
    </div>
  );
}
