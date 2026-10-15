/**
 * The question box: text, the paperclip for PDFs, attachment chips and the model picker. Sending is
 * disabled while the model is unavailable or an attachment is still being read; Enter sends,
 * Shift+Enter starts a new line.
 */
import { ArrowUp, Paperclip } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import type { ModelInfo } from "../api";
import type { Attachment } from "../types";
import { isPending } from "../types";
import { useT } from "../i18n";
import { Button, FileButton, IconButton, TextArea } from "../ui";
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
  const m = useT();
  const [text, setText] = useState("");
  const waiting = attachments.some(isPending);
  const reason = disabledReason ?? (waiting ? m.waitingForDocuments : null);
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
        <FileButton accept={["application/pdf", ".pdf"]} multiple onSelect={onAttach}>
          <IconButton label={m.attachPdf}><Paperclip size={18} aria-hidden /></IconButton>
        </FileButton>
        <TextArea label={m.yourQuestion} hideLabel value={text} onChange={setText} onKeyDown={onKey}
                  placeholder={m.askPlaceholder} className="composer-field" />
        <ModelPicker models={models} chosen={chosenModel} onChoose={onChooseModel} />
        <Button variant="plain" className="send-button" onPress={send} isDisabled={!canSend} aria-label={m.send}>
          <ArrowUp size={16} strokeWidth={2.2} aria-hidden />
        </Button>
      </div>
      <p className="composer-hint caption" role="status">
        {reason ?? note ?? m.composerHint}
      </p>
    </div>
  );
}
