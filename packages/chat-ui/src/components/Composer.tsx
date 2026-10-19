/**
 * The question box: text, the paperclip for documents, attachment chips, the case's playbooks (a teal
 * chip with a menu; docs/design/sidebar.md) and the model picker. Sending is disabled while the
 * model is unavailable or an attachment is still being read; Enter sends, Shift+Enter starts a new line.
 */
import { AlertTriangle, ArrowUp, Check, ChevronDown, ClipboardList, Folder, Paperclip, Square } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import type { ModelInfo, PlaybookInfo } from "../api";
import type { Attachment } from "../types";
import { isPending } from "../types";
import { lang, useT } from "../i18n";
import { ACCEPTED_FILES } from "../lib/formats";
import { playbookWords } from "../lib/playbooks";
import { ActionMenu, Button, FileButton, IconButton, TextArea } from "../ui";
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
  /** An attachment that looks like sūveryn's own output: use it as a source anyway, or delete it. */
  onUseAsSource?: (key: string) => void;
  onDeleteAttachment?: (key: string) => void;
  onSend: (text: string) => void;
  /** Stop the answer being written (docs/design/sidebar.md §5): in the send button's place, and Esc. */
  onStop?: () => void;
  /** The open case's reference, shown as a chip; nothing in the personal space. */
  caseReference?: string | null;
  /** The open case's type as shown ("Verkoop"), for the playbook menu's title. */
  caseType?: string | null;
  /** The playbooks that fit the open case (empty: no chip), and what to do when one is chosen. */
  playbooks?: PlaybookInfo[];
  onPlaybook?: (slug: string) => void;
};

export function Composer({ attachments, models, chosenModel, onChooseModel, disabledReason, busy, onAttach,
                          onRemoveAttachment, onUseAsSource, onDeleteAttachment, onSend, onStop, caseReference, caseType,
                          playbooks = [], onPlaybook }: Props) {
  const m = useT();
  const [text, setText] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const waiting = attachments.some(isPending);
  const reason = disabledReason ?? (waiting ? m.waitingForDocuments : null);
  const note = loadingNote(models, chosenModel);
  const canSend = !reason && !busy && text.trim().length > 0;

  const send = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };
  // Stopping: the button gives way to send, so the focus goes to the question box, where the next
  // question may already be typed (the input stays usable while an answer is written).
  const stop = () => {
    onStop?.();
    wrap.current?.querySelector("textarea")?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();  // while an answer is written this does nothing: the text waits
    } else if (e.key === "Escape" && busy && onStop) {
      e.preventDefault();
      stop();
    }
  };

  return (
    <div className="composer-wrap" ref={wrap}>
      {attachments.length > 0 && (
        <div className="attachments pending">
          {attachments.map((a) => <AttachmentChip key={a.key} a={a} onRemove={() => onRemoveAttachment(a.key)}
                                                  onUseAsSource={onUseAsSource && (() => onUseAsSource(a.key))}
                                                  onDelete={onDeleteAttachment && (() => onDeleteAttachment(a.key))} />)}
        </div>
      )}
      {/* The canvas's composer: the question on top, the tools under it (docs/design/sidebar.md). */}
      <div className="composer">
        <TextArea label={m.yourQuestion} hideLabel value={text} onChange={setText} onKeyDown={onKey}
                  placeholder={busy ? m.keepTyping : m.askPlaceholder} className="composer-field" />
        <div className="composer-tools">
          <FileButton accept={ACCEPTED_FILES} multiple onSelect={onAttach}>
            <IconButton size="small" label={m.attachDocument}><Paperclip size={16} aria-hidden /></IconButton>
          </FileButton>
          {caseReference && <span className="chip-case"><Folder size={13} aria-hidden /> {m.caseLabel(caseReference)}</span>}
          {playbooks.length > 0 && onPlaybook && (
            <ActionMenu className="chip-playbook" aria-label={m.playbookChip} menuLabel={m.playbookMenu} placement="top start"
                        popoverClassName="playbook-menu"
                        header={<span className="ui-menu-eyebrow">{m.playbookMenuTitle(caseReference ?? "", caseType ?? "")}</span>}
                        footer={m.playbookMenuFooter}
                        entries={playbooks.map((p) => ({
                          id: p.slug, label: playbookWords(p, lang()).title, icon: <ClipboardList size={16} />,
                          description: [playbookWords(p, lang()).summary, `v${p.version}`].filter(Boolean).join(" · "),
                          meta: p.covered ? m.covered : m.notCovered, metaTone: p.covered ? "teal" as const : "warn" as const,
                          metaIcon: p.covered ? <Check size={13} aria-hidden /> : <AlertTriangle size={13} aria-hidden />,
                        }))}
                        onAction={onPlaybook}>
              <ClipboardList size={13} aria-hidden /> {m.playbook} <ChevronDown size={13} aria-hidden />
            </ActionMenu>
          )}
          <span className="composer-space" />
          <ModelPicker models={models} chosen={chosenModel} onChoose={onChooseModel} />
          {busy && onStop
            ? <Button variant="plain" className="send-button" onPress={stop} aria-label={m.stop} title={m.stopTitle}>
                <Square size={12} fill="currentColor" strokeWidth={0} aria-hidden />
              </Button>
            : <Button variant="plain" className="send-button" onPress={send} isDisabled={!canSend} aria-label={m.send}>
                <ArrowUp size={16} strokeWidth={2.2} aria-hidden />
              </Button>}
        </div>
      </div>
      <p className="composer-hint caption" role="status">
        {reason ?? note ?? m.staysOnServer}
      </p>
    </div>
  );
}
