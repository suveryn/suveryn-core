/**
 * The person's own settings (docs/design/chat-ui.md): their picture (the avatar dialog) and their
 * password, which lives in the office's sign-in (Keycloak's account console, `account_url`): a link
 * that opens in a new tab, since the appliance never sees a password. With sign-in off there is none.
 * And the default thinking mode for new conversations (§5), kept in this browser (lib/thinking.ts),
 * when a model can think.
 */
import { ExternalLink, ImagePlus } from "lucide-react";
import { useState } from "react";
import type { Me } from "../api";
import { useT } from "../i18n";
import { setThinkingDefault, thinkingDefault } from "../lib/thinking";
import { Avatar, Button, Dialog, LinkButton, Segmented, TextButton } from "../ui";

export function SettingsDialog({ open, me, onClose, onPicture, thinks = false }: {
  open: boolean; me: Me; onClose: () => void; onPicture: () => void;
  /** An installed model can think: the default thinking mode is offered. */
  thinks?: boolean;
}) {
  const m = useT();
  const [thorough, setThorough] = useState(thinkingDefault);
  return (
    <Dialog isOpen={open} onClose={onClose} title={m.settings} actions={<TextButton autoFocus onPress={onClose}>{m.close}</TextButton>}>
      <div className="settings-rows">
        <div className="settings-row">
          <Avatar name={me.name} sub={me.sub} etag={me.avatar} admin={me.admin} adminLabel={m.administrator} size="large" />
          <div className="settings-text">
            <h2 className="label">{m.settingsPicture}</h2>
            <p className="caption">{m.avatarIntro}</p>
          </div>
          <Button size="small" onPress={onPicture}><ImagePlus size={14} aria-hidden /> {m.changePicture}</Button>
        </div>
        <div className="settings-row">
          <div className="settings-text">
            <h2 className="label">{m.settingsPassword}</h2>
            <p className="caption">{me.account_url ? m.passwordWhere : m.passwordUnavailable}</p>
          </div>
          {me.account_url && (
            <LinkButton href={me.account_url} variant="secondary" className="settings-link" newTab>
              <ExternalLink size={14} aria-hidden /> {m.changePassword}
            </LinkButton>
          )}
        </div>
        {thinks && (
          <div className="settings-row">
            <div className="settings-text">
              <h2 className="label">{m.settingsThinking}</h2>
              <p className="caption">{m.settingsThinkingHint}</p>
            </div>
            <Segmented label={m.settingsThinking} value={thorough ? "thorough" : "fast"}
                       onChange={(v) => { setThorough(v === "thorough"); setThinkingDefault(v === "thorough"); }}
                       options={[{ value: "fast", label: m.fast }, { value: "thorough", label: m.thorough }]} />
          </div>
        )}
      </div>
    </Dialog>
  );
}
