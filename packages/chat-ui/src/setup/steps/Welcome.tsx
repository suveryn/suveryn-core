/** Setup screen 0: Welcome (design web-00-welcome.html). What setup does, and two things to know first. */
import { Fingerprint, Lock } from "lucide-react";
import { Button, Notice } from "../../ui";
import { useText } from "../text";

export function Welcome({ onStart, headingId }: { onStart: () => void; headingId: string }) {
  const t = useText();
  return (
    <div className="setup-welcome">
      <h1 id={headingId} className="setup-title setup-centred">{t.welcomeTitle}</h1>
      <p className="setup-lead setup-centred">{t.welcomeLead}</p>
      <div className="setup-stack">
        <Notice icon={<Lock size={16} />} title={t.welcomeOpenTitle}>{t.welcomeOpenText}</Notice>
        <Notice icon={<Fingerprint size={16} />} title={t.welcomeCheckTitle}>{t.welcomeCheckText}</Notice>
      </div>
      <ol className="setup-step-list" aria-label={t.welcomeSteps}>
        {t.stepNames.map((n) => <li key={n}><span>{n}</span></li>)}
      </ol>
      <Button variant="primary" className="setup-wide" onPress={onStart}>{t.getStarted}</Button>
    </div>
  );
}
