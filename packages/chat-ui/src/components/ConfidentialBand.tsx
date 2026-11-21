/**
 * The band above a strictly confidential case (docs/design/chat-ui.md §11, artboards 23 and 24): in
 * inverted ink, so it turns light-on-dark in the dark theme by itself, with the key and what the
 * label does (not how secret the case is). At its end, who can change it (board 80, suveryn-tracker#230):
 * for the case's manager *Change access*, which opens the case's settings at its access; for everyone
 * else the manager's name. On a narrow screen: the key, the label and *What does this mean?*, which opens
 * the three rules with the same line under them.
 */
import { FolderKey } from "lucide-react";
import { useState } from "react";
import { useT } from "../i18n";
import { Dialog, TextButton } from "../ui";

export function ConfidentialBand({ narrow, onChangeAccess = null, manager = "" }: {
  narrow: boolean;
  /** The manager's way to the setting (null for everyone else). */
  onChangeAccess?: (() => void) | null;
  /** The case manager's name, said to everyone else. */
  manager?: string;
}) {
  const m = useT();
  const [open, setOpen] = useState(false);
  const who = onChangeAccess
    ? <TextButton className="confidential-change" onPress={() => { setOpen(false); onChangeAccess(); }}>{m.changeAccess}</TextButton>
    : manager ? <span className="confidential-who">{m.onlyManagerChanges({ name: manager })}</span> : null;
  return (
    <div className="confidential-band" role="note" aria-label={m.strictlyConfidential}>
      <FolderKey size={14} aria-hidden />
      <b>{m.strictlyConfidential}</b>
      {narrow ? <>
        <TextButton className="confidential-what" onPress={() => setOpen(true)}>{m.confidentialWhat}</TextButton>
        <Dialog isOpen={open} onClose={() => setOpen(false)} kind="information" title={m.strictlyConfidential} closeLabel={m.close}>
          <ul className="confidential-rules">{m.confidentialRules.split(" · ").map((r) => <li key={r}>{r}</li>)}</ul>
          {who && <p className="confidential-sheet-who">{who}</p>}
        </Dialog>
      </> : <>
        {/* the rules give way with an ellipsis when the band is short; who can change it doesn't */}
        <span className="confidential-rules-line">· {m.confidentialRules}</span>
        {who}
      </>}
    </div>
  );
}
