/**
 * The question box: text, the paperclip for documents, attachment chips, the case's playbooks (a teal
 * chip with a menu; docs/design/chat-ui.md) and the model picker. Sending is disabled while the
 * model is unavailable or an attachment is still being read; Enter sends, Shift+Enter starts a new line.
 *
 * On a narrow screen (`compact`, §2) it is one pill: the question, one "+" menu for the document, the
 * playbook and the model, and send. On the start screen, "Work in a case" chooses a case (§2, artboard 01).
 */
import {
  ArrowUp, Check, ChevronDown, ClipboardList, Files, Folder, FolderPlus, Lock, Paperclip, Plus, Square, TriangleAlert
} from "lucide-react";
import { keepDraft, readDraft } from "../lib/draft";
import { useRef, useState, type KeyboardEvent } from "react";
import type { Case, ModelInfo, PlaybookInfo } from "../api";
import type { Attachment } from "../types";
import { isPending } from "../types";
import { lang, useT } from "../i18n";
import { ACCEPTED_FILES } from "../lib/formats";
import { playbookWords } from "../lib/playbooks";
import { modelName } from "../lib/model";
import { ActionMenu, Button, DocumentPicker, IconButton, TextArea, useFilePicker, type MenuEntry, type PickItem } from "../ui";
import { AttachmentCard } from "./Chips";
import { defaultModel, loadingNote, ModelPicker } from "./ModelPicker";

/** Ask about (docs/design/chat-ui.md §10): the case's documents to choose from, and the choice. */
export type AskAbout = {
  items: PickItem[];
  selected: string[];
  /** The chosen documents' names, in order, for the button. */
  names: string[];
  onChange: (ids: string[]) => void;
};

type Props = {
  /** In a case where the person may ask: Ask about. */
  askAbout?: AskAbout | null;
  /** In a case: the line under the box, when the choice changes it ("Answers use only …"). */
  caseNote?: string | null;
  /** The person can't ask here at all (someone else's shared conversation, a closed case, a reader):
   *  the box takes no typing. Not for a passing reason such as the server being unreachable, when
   *  the typed text waits to be sent. */
  locked?: boolean;
  attachments: Attachment[];
  models: ModelInfo[];            // installed models (GET /v1/models)
  chosenModel: string | null;     // null: the default model
  onChooseModel: (id: string) => void;
  /** *Thorough* for this conversation (docs/design/chat-ui.md §5). */
  thinking: boolean;
  onThinking: (on: boolean) => void;
  disabledReason: string | null; // why sending is impossible right now, shown under the input
  busy: boolean;                 // an answer is being written
  onAttach: (files: File[]) => void;
  onRemoveAttachment: (key: string) => void;
  /** An attachment that looks like sūveryn's own output: use it as a source anyway, or delete it. */
  onUseAsSource?: (key: string) => void;
  onDeleteAttachment?: (key: string) => void;
  onSend: (text: string) => void;
  /** Stop the answer being written (docs/design/chat-ui.md §5): in the send button's place, and Esc. */
  onStop?: () => void;
  /** The open case's reference: the question box and the line under it name the case (§5); null in the personal space. */
  caseReference?: string | null;
  /** The open case's type as shown ("Verkoop"), for the playbook menu's title. */
  caseType?: string | null;
  /** The playbooks that fit the open case (empty: no chip), and what to do when one is chosen. */
  playbooks?: PlaybookInfo[];
  onPlaybook?: (slug: string) => void;
  /** One pill with a "+" menu (narrow screens). */
  compact?: boolean;
  /** The line under the box instead of the default (which says where answers come from). */
  hint?: string | null;
  placeholder?: string;
  /** The start screen's "Work in a case": the open cases to choose from, and a new one. */
  workInCase?: { cases: Case[]; onChoose: (c: Case) => void; onNew: (() => void) | null } | null;
};

const CASES_IN_CHIP = 8;

export function Composer({ askAbout = null, caseNote = null, locked = false, attachments, models, chosenModel, onChooseModel, thinking, onThinking, disabledReason, busy, onAttach,
                          onRemoveAttachment, onUseAsSource, onDeleteAttachment, onSend, onStop, caseReference, caseType,
                          playbooks = [], onPlaybook, compact = false, hint = null, placeholder, workInCase = null }: Props) {
  const m = useT();
  // The draft outlives a sign-in in this tab (lib/draft.ts).
  const [text, setTextState] = useState(readDraft);
  const setText = (t: string) => { setTextState(t); keepDraft(t); };
  const wrap = useRef<HTMLDivElement>(null);
  const picker = useFilePicker(ACCEPTED_FILES, true, onAttach);
  const waiting = attachments.some(isPending);
  // A document still being read doesn't hold the question back: it counts for the next one once ready (§5).
  const reason = disabledReason;
  const note = loadingNote(models, chosenModel);
  const canSend = !reason && !busy && text.trim().length > 0;
  const attachLabel = caseReference ? m.attachToCase(caseReference) : m.attachDocument;

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

  const playbookEntries: MenuEntry[] = playbooks.map((p) => ({
    id: p.slug, label: playbookWords(p, lang()).title, icon: <ClipboardList size={16} />,
    description: [playbookWords(p, lang()).summary, `v${p.version}`].filter(Boolean).join(" · "),
    meta: p.covered ? m.covered : m.notCovered, metaTone: p.covered ? "teal" as const : "warn" as const,
    metaIcon: p.covered ? <Check size={13} aria-hidden /> : <TriangleAlert size={13} aria-hidden />,
  }));
  // The narrow composer's "+": the document, the case's playbooks and the model, in one menu.
  const current = models.find((x) => x.id === chosenModel) ?? defaultModel(models);
  const moreEntries: MenuEntry[] = [
    { id: "attach", label: attachLabel, icon: <Paperclip size={16} /> },
    ...(playbooks.length > 0 && onPlaybook ? [{ heading: m.playbook, items: playbookEntries.map((e) => (e === "-" || "heading" in e ? e : { ...e, id: `playbook:${e.id}` })) }] : []),
    ...(models.length > 1 ? [{ id: "model", label: m.model, meta: modelName(current?.id)?.family, submenu: models.map((x) => ({
      id: `model:${x.id}`, label: modelName(x.id)?.full ?? x.id,
      description: (x.loaded ? m.modelReady : m.modelLoadsWhenChosen) + (x.thinks ? ` · ${m.modelThinks}` : ""),
    })), selected: current ? `model:${current.id}` : undefined }] : []),
    // Fast or Thorough, with a model that can think (the dialog says why not for one that can't)
    ...(current?.thinks ? [{ id: "thinking", label: m.thinkingLabel, meta: thinking ? m.thorough : m.fast, submenu: [
      { id: "think:fast", label: m.fast, description: m.fastHint },
      { id: "think:thorough", label: m.thorough, description: m.thoroughHint },
    ], selected: thinking ? "think:thorough" : "think:fast" }] : []),
  ];
  const onMore = (id: string) => {
    if (id === "attach") picker.open();
    else if (id.startsWith("playbook:")) onPlaybook?.(id.slice(9));
    else if (id.startsWith("model:")) onChooseModel(id.slice(6));
    else if (id.startsWith("think:")) onThinking(id === "think:thorough");
  };
  // The start screen's "Work in a case": the most recent open cases, then a new one.
  const caseEntries: MenuEntry[] = workInCase ? [
    ...workInCase.cases.slice(0, CASES_IN_CHIP).map((c) => ({ id: `case:${c.id}`, label: `${c.reference} ${c.name}`, icon: <Folder size={16} /> })),
    ...(workInCase.onNew ? [...(workInCase.cases.length ? ["-" as const] : []), { id: "new", label: m.newCase, icon: <FolderPlus size={16} />, description: m.newCaseHint }] : []),
  ] : [];
  const onCaseChoice = (id: string) => {
    if (id === "new") workInCase?.onNew?.();
    else workInCase?.onChoose(workInCase.cases.find((c) => `case:${c.id}` === id)!);
  };

  // Ask about: beside the paperclip; on a narrow screen above the pill, full width, opening a sheet.
  const picker2 = askAbout && caseReference && (
    <DocumentPicker className="chip-about" narrow={compact} items={askAbout.items} selected={askAbout.selected}
                    onChange={askAbout.onChange} label={m.askAboutTitle} triggerLabel={m.askAboutLabel(askAbout.selected.length)}
                    allLabel={m.askAboutAllIn(caseReference)} allMeta={m.askAboutSources(askAbout.items.length)}
                    chosenHeading={m.askAboutChosen} othersHeading={(q, n) => (q ? m.askAboutMatching(q, n) : null)}
                    searchLabel={m.askAboutSearch} doneLabel={m.askAboutDone}
                    action={{ label: m.askAboutUpload, description: m.askAboutUploadHint, onPress: () => picker.open() }}
                    trigger={<>
                      <Files size={14} aria-hidden />
                      <span className="chip-about-dim">{m.askAbout}</span>
                      <span className="chip-about-value">{askAbout.names.length === 0 ? m.askAboutAll
                        : askAbout.names.length === 1 ? askAbout.names[0] : m.askAboutCount(askAbout.names.length)}</span>
                      <ChevronDown size={12} aria-hidden />
                    </>} />
  );
  // The cards sit inside the question box; on a narrow screen, where the box is one pill, above it.
  const cards = attachments.length > 0 && (
      <ul className="attachment-cards" aria-label={m.attachedDocuments}>
        {attachments.map((a) => <AttachmentCard key={a.key} a={a} onRemove={() => onRemoveAttachment(a.key)}
                                                onUseAsSource={onUseAsSource && (() => onUseAsSource(a.key))}
                                                onDelete={onDeleteAttachment && (() => onDeleteAttachment(a.key))}
                                                onReplace={(files) => { onRemoveAttachment(a.key); onAttach(files); }} />)}
      </ul>
  );
  return (
    <div className="composer-wrap" ref={wrap}>
      {compact && picker2}
      {compact && cards}
      {/* The canvas's composer: the question on top, the tools under it (docs/design/chat-ui.md). On a
          narrow screen one pill: the question, "+" and send. */}
      <div className="composer" data-compact={compact || undefined}>
        {!compact && cards}
        <TextArea label={caseReference ? m.questionInCase(caseReference) : m.yourQuestion} hideLabel value={text} onChange={setText} onKeyDown={onKey}
                  isReadOnly={locked}
                  placeholder={locked ? "" : busy ? m.keepTyping : placeholder ?? (caseReference ? m.askInCase(caseReference) : m.askPlaceholder)} className="composer-field" />
        <div className="composer-tools">
          {compact ? <>
            {picker.input}
            <ActionMenu className="composer-more" aria-label={m.composerMore} menuLabel={m.composerMore} placement="top end"
                        entries={moreEntries} onAction={onMore}>
              <Plus size={18} aria-hidden />
            </ActionMenu>
          </> : <>
          {picker.input}
          <IconButton size="small" label={attachLabel} onPress={() => picker.open()}><Paperclip size={16} aria-hidden /></IconButton>
          {picker2}
          {workInCase && (
            <ActionMenu className="chip-work-in-case" aria-label={m.workInCaseMenu} menuLabel={m.workInCaseMenu} placement="bottom start"
                        entries={caseEntries} onAction={onCaseChoice}>
              <FolderPlus size={13} aria-hidden /> {m.workInCase}
            </ActionMenu>
          )}
          {playbooks.length > 0 && onPlaybook && (
            <ActionMenu className="chip-playbook" aria-label={m.playbookChip} menuLabel={m.playbookMenu} placement="top start"
                        popoverClassName="playbook-menu"
                        header={<span className="ui-menu-eyebrow">{m.playbookMenuTitle(caseReference ?? "", caseType ?? "")}</span>}
                        entries={playbookEntries}
                        onAction={onPlaybook}>
              <ClipboardList size={13} aria-hidden /> {m.playbook} <ChevronDown size={13} aria-hidden />
            </ActionMenu>
          )}
          <span className="composer-space" />
          <ModelPicker models={models} chosen={chosenModel} onChoose={onChooseModel} thinking={thinking} onThinking={onThinking} />
          </>}
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
        {/* Where answers come from (§5): only this case's documents, or a personal chat only you see. */}
        {reason ?? note ?? (waiting ? m.readingCountsLater : null) ?? (hint ? <><Lock size={12} aria-hidden /> {hint}</>
          : caseReference ? caseNote ?? m.caseOnlyDocuments(caseReference) : <><Lock size={12} aria-hidden /> {m.personalHint}</>)}
      </p>
    </div>
  );
}
