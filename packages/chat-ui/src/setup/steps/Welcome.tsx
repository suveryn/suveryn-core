/** Setup screen 0: Welcome (design web-00-welcome.html). What setup does, and two things to know first;
 *  or, on a replacement appliance, restoring the office's backup instead (#56). */
import { FingerprintPattern, Lock } from "lucide-react";
import { Button, Notice } from "../../ui";
import { useText } from "../i18n";

export function Welcome({ onStart, onRestore, headingId }: { onStart: () => void; onRestore: () => void; headingId: string }) {
  const t = useText();
  return (
    <div className="setup-welcome">
      <h1 id={headingId} className="setup-title setup-centred">{t.welcomeTitle}</h1>
      <p className="setup-lead setup-centred">{t.welcomeLead}</p>
      <div className="setup-stack">
        <Notice icon={<Lock size={16} />} title={t.welcomeOpenTitle}>{t.welcomeOpenText}</Notice>
        <Notice icon={<FingerprintPattern size={16} />} title={t.welcomeCheckTitle}>{t.welcomeCheckText}</Notice>
      </div>
      <ol className="setup-step-list" aria-label={t.welcomeSteps}>
        {t.stepNames.map((n) => <li key={n}><span>{n}</span></li>)}
      </ol>
      <Button variant="primary" className="setup-wide" onPress={onStart}>{t.getStarted}</Button>
      <p className="setup-detail-note setup-centred setup-restore-hint">{t.welcomeRestoreHint}</p>
      <Button className="setup-wide" onPress={onRestore}>{t.welcomeRestore}</Button>
    </div>
  );
}
