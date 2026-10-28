/**
 * The conversation menu's two dialogs (docs/design/chat-ui.md §4): *Rename* and *Move to a case*. The
 * server decides (routes/conversations.py); these only ask, and say what went wrong.
 */
import { AlertCircle, FolderInput, MessageSquare, Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { moveConversation, renameConversation, type Case, type ConversationSummary } from "../api";
import { useT } from "../i18n";
import { listedTitle } from "../lib/conversations";
import { conversationActions, moveTargets, type ConversationAction } from "../lib/conversationActions";
import { Button, Dialog, Form, InlineNotice, SelectField, TextButton, TextField, type MenuEntry } from "../ui";

const MAX_TITLE = 200;

/** A conversation's menu (the column's rows and the overview's), from lib/conversationActions.ts: *Pin*
 *  or *Unpin*, *Rename*, *Move to a case*, then *Delete* apart. Disabled, never hidden. */
export function conversationMenu(c: ConversationSummary, me: string | undefined, m: ReturnType<typeof useT>, withOpen = false): MenuEntry[] {
  const icons: Record<ConversationAction, ReactNode> = {
    open: <MessageSquare size={16} />, pin: <Pin size={16} />, unpin: <PinOff size={16} />, rename: <Pencil size={16} />,
    move: <FolderInput size={16} />, delete: <Trash2 size={16} />,
  };
  const labels: Record<ConversationAction, string> = {
    open: m.open, pin: m.pin, unpin: m.unpin, rename: m.rename, move: m.moveToCase, delete: m.delete,
  };
  const entries: MenuEntry[] = [];
  for (const a of conversationActions(c, me, withOpen)) {
    if (a.id === "delete") entries.push("-");
    entries.push({ id: a.id, label: labels[a.id], icon: icons[a.id], isDisabled: a.disabled,
                   ...(a.reason === "followsCase" ? { description: m.pinCaseInstead } : {}) });
  }
  return entries;
}

export function RenameConversationDialog({ conversation, onDone, onCancel }: {
  conversation: ConversationSummary | null; onDone: (c: ConversationSummary) => void; onCancel: () => void;
}) {
  const m = useT();
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (conversation) { setTitle(conversation.title ?? ""); setError(null); setBusy(false); }
  }, [conversation]);
  const check = (): Record<string, string> => (title.trim() ? {} : { title: m.required });
  const save = async () => {
    if (!conversation) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await renameConversation(conversation.id, title.trim()));
    } catch (e) {
      setError(m.renameFailed((e as Error).message));
      setBusy(false);
    }
  };
  return (
    <Dialog isOpen={!!conversation} onClose={onCancel} busy={busy} title={m.renameTitle} actions={<>
      <Button variant="primary" type="submit" form="rename-conversation" isDisabled={busy}><Pencil size={16} aria-hidden /> {m.save}</Button>
      <TextButton onPress={onCancel} isDisabled={busy}>{m.cancel}</TextButton>
    </>}>
      <Form id="rename-conversation" check={check} onValid={save} className="case-form">
        <TextField name="title" label={m.renameLabel} value={title} onChange={setTitle} autoFocus maxLength={MAX_TITLE} />
        {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      </Form>
    </Dialog>
  );
}

export function MoveConversationDialog({ conversation, cases, onDone, onCancel }: {
  conversation: ConversationSummary | null; cases: Case[]; onDone: (c: ConversationSummary) => void; onCancel: () => void;
}) {
  const m = useT();
  const targets = moveTargets(cases);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (conversation) { setTarget(""); setError(null); setBusy(false); }
  }, [conversation]);
  const chosen = target || targets[0]?.id || "";
  const move = async () => {
    if (!conversation || !chosen) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await moveConversation(conversation.id, chosen));
    } catch (e) {
      setError(m.moveFailed((e as Error).message));
      setBusy(false);
    }
  };
  return (
    <Dialog isOpen={!!conversation} onClose={onCancel} busy={busy}
            title={conversation ? m.moveTitle(listedTitle(conversation)) : m.moveToCase} actions={<>
      {/* Cancel first when there's nowhere to go: the dialog focuses it */}
      {targets.length > 0 && <Button variant="primary" autoFocus onPress={move} isDisabled={busy}><FolderInput size={16} aria-hidden /> {m.moveButton}</Button>}
      <TextButton onPress={onCancel} isDisabled={busy} autoFocus={targets.length === 0}>{m.cancel}</TextButton>
    </>}>
      {targets.length > 0
        ? <SelectField name="case" label={m.moveLabel} value={chosen} onChange={setTarget}
                       options={targets.map((c) => ({ id: c.id, label: `${c.reference} ${c.name}` }))} />
        : <p>{m.moveNoCase}</p>}
      <p className="caption">{targets.find((c) => c.id === chosen)?.confidential ? m.moveHintConfidential : m.moveHint}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
    </Dialog>
  );
}
