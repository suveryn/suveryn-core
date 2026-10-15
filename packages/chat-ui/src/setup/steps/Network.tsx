/**
 * Setup step 1: Network (design web-01-network*.html). The name and address come from the console
 * installer and are only shown here; the choice is the internet access: Connected (approved
 * destinations only, or everything) or Air-gapped.
 */
import { Globe, Network as NetworkIcon, Server, SquareTerminal, WifiOff } from "lucide-react";
import { useState } from "react";
import { Button, Chips, Facts, Form, RadioCards, RadioList } from "../../ui";
import type { Answers, NetworkMode, Outgoing, SetupState } from "../api";
import { useText } from "../text";

type Props = {
  state: SetupState;
  answers: Answers["network"];
  onDone: (network: Answers["network"]) => void;
  headingId: string;
};

export function Network({ state, answers, onDone, headingId }: Props) {
  const t = useText();
  const [mode, setMode] = useState<NetworkMode>(answers.mode);
  const [outgoing, setOutgoing] = useState<Outgoing>(answers.outgoing);

  return (
    <Form check={() => ({})} onValid={() => onDone({ mode, outgoing })} aria-labelledby={headingId}>
      <h1 id={headingId} className="setup-title">{t.networkTitle}</h1>
      <p className="setup-lead">{t.networkLead}</p>

      <h2 className="setup-subtitle">{t.setDuringInstallation}</h2>
      <div className="setup-block">
        <Facts
          facts={[
            { icon: <Server size={18} />, label: t.name, value: state.name, detail: `${state.name}.local` },
            { icon: <NetworkIcon size={18} />, label: t.address, value: state.address,
              detail: t.addressDetail(state.dhcp, state.gateway, state.dns) },
          ]}
          footer={<><SquareTerminal size={16} aria-hidden /><span>{t.changeOnConsole}</span></>}
        />
      </div>

      <h2 className="setup-subtitle" id={`${headingId}-access`}>{t.internetAccess}</h2>
      <p className="setup-sublead">{t.internetAccessLead}</p>
      <RadioCards
        label={t.internetAccess}
        name="mode"
        value={mode}
        onChange={(v) => setMode(v as NetworkMode)}
        choices={[
          { value: "connected", title: t.connected, description: t.connectedDesc, icon: <Globe size={18} /> },
          { value: "air-gapped", title: t.airGapped, description: t.airGappedDesc, icon: <WifiOff size={18} /> },
        ]}
      />
      {mode === "connected" && (
        <div className="setup-detail">
          <p className="ui-eyebrow setup-detail-label" aria-hidden>{t.outgoing}</p>
          <RadioList
            label={t.outgoing}
            name="outgoing"
            value={outgoing}
            onChange={(v) => setOutgoing(v as Outgoing)}
            choices={[
              { value: "approved", title: t.approvedOnly, description: t.approvedOnlyDesc,
                after: <Chips label={t.approvedList} items={[t.approvedUpdates, t.approvedConnectors]} /> },
              { value: "all", title: t.allowAll, description: t.allowAllDesc },
            ]}
          />
          <p className="setup-detail-note">{t.changeLater}</p>
        </div>
      )}

      <div className="setup-footer">
        <span />
        <Button type="submit" variant="primary">{t.continue}</Button>
      </div>
    </Form>
  );
}
