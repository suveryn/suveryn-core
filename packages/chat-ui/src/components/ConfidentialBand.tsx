/**
 * The band above a strictly confidential case (docs/design/sidebar.md §11, artboards 23 and 24): in
 * inverted ink, so it turns light-on-dark in the dark theme by itself, with the key and what the
 * label does (not how secret the case is). On a narrow screen: the key, the label and *What does this
 * mean?*, which opens the three rules.
 */
import { FolderKey } from "lucide-react";
import { useState } from "react";
import { useT } from "../i18n";
import { Dialog, TextButton } from "../ui";

export function ConfidentialBand({ narrow }: { narrow: boolean }) {
  const m = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="confidential-band" role="note" aria-label={m.strictlyConfidential}>
      <FolderKey size={14} aria-hidden />
      <b>{m.strictlyConfidential}</b>
      {narrow ? <>
        <TextButton className="confidential-what" onPress={() => setOpen(true)}>{m.confidentialWhat}</TextButton>
        <Dialog isOpen={open} onClose={() => setOpen(false)} title={m.strictlyConfidential}
                actions={<TextButton onPress={() => setOpen(false)}>{m.close}</TextButton>}>
          <ul className="confidential-rules">{m.confidentialRules.split(" · ").map((r) => <li key={r}>{r}</li>)}</ul>
        </Dialog>
      </> : <span className="confidential-rules-line">· {m.confidentialRules}</span>}
    </div>
  );
}
