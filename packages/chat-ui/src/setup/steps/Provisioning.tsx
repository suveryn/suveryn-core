/**
 * Setup screens 7 and 8: Provisioning and Complete (design web-07-provisioning.html,
 * web-08-complete*.html). Provisioning asks the appliance for its progress every second and says
 * each new step out loud (a polite live region); if a step fails, it says where and offers Try again.
 * Complete shows what was set up, the outgoing-traffic check, and where to sign in from now on.
 */
import { Check, CircleAlert, Info, LoaderCircle, Lock, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, LinkButton, Notice, Progress, StatusList, type StatusItem } from "../../ui";
import { getProgress, startProvisioning, type Progress as ProgressState, type SetupState, type StepId } from "../api";
import { useText, type Text } from "../i18n";

function items(p: ProgressState, state: SetupState, t: Text): StatusItem[] {
  return p.steps.map((s) => {
    let label = t.stepLabel[s.id];
    let detail: string | undefined = s.id === "models" ? t.modelsOnDisk(state.models.length) : t.stepDetail[s.id as Exclude<StepId, "models">];
    if (s.id === "models" && s.state === "done") detail = state.models.join(", ");
    if (s.id === "outgoing" && p.outgoing) [label, detail] = t.outgoingResult[p.outgoing];
    const failedCheck = s.id === "outgoing" && p.outgoing === "not_limited";
    return { id: s.id, label, detail, state: failedCheck ? "failed" : s.state, stateText: t.stateText[failedCheck ? "failed" : s.state] };
  });
}

export function Provisioning({ state, onDone, headingId }: { state: SetupState; onDone: (p: ProgressState) => void; headingId: string }) {
  const t = useText();
  const [progress, setProgress] = useState<ProgressState | null>(state.provisioning);
  const [restart, setRestart] = useState(0);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async (first: boolean) => {
      try {
        // Start it, unless it already runs (a reload) or stopped (then Try again starts it).
        const p = first && (!state.provisioning || restart > 0) ? await startProvisioning() : await getProgress();
        if (stop) return;
        setProgress(p);
        if (p.state === "done") { onDone(p); return; }
        if (p.state === "failed") return;
      } catch { /* the appliance is busy (services restarting): ask again */ }
      if (!stop) timer = setTimeout(() => poll(false), 1000);
    };
    poll(true);
    return () => { stop = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restart]);

  const steps = progress?.steps ?? [];
  const done = steps.filter((s) => s.state === "done").length;
  const running = steps.find((s) => s.state === "running");
  const failed = steps.find((s) => s.state === "failed");

  return (
    <div className="setup-final">
      <span className="setup-final-icon" aria-hidden>{failed ? <CircleAlert size={22} /> : <LoaderCircle size={22} className="ui-spin" />}</span>
      <h1 id={headingId} className="setup-title setup-centred">{t.provTitle}</h1>
      <p className="setup-lead setup-centred">{t.provLead}</p>
      <div className="setup-stack">
        <div className="setup-progress">
          <Progress value={steps.length ? (done / steps.length) * 100 : 0} label={t.provProgress}
                    valueText={t.provDone(done, steps.length || 5)} />
          <p className="setup-detail-note" aria-live="polite">{running ? t.stepNow[running.id] : ""}</p>
        </div>
        {progress && <StatusList items={items(progress, state, t)} />}
        {failed ? (
          <>
            <div role="alert">
              <Notice icon={<TriangleAlert size={16} />} tone="warning" title={t.provFailedTitle}>
                {t.provFailedText(t.stepLabel[failed.id])}
              </Notice>
            </div>
            <Button variant="primary" className="setup-wide" onPress={() => setRestart((r) => r + 1)}>{t.tryAgain}</Button>
          </>
        ) : (
          <Notice icon={<Info size={16} />}><b className="setup-strong">{t.doNotTurnOff}</b> {t.doNotTurnOffMore}</Notice>
        )}
      </div>
    </div>
  );
}

export function Complete({ state, progress, headingId }: { state: SetupState; progress: ProgressState; headingId: string }) {
  const t = useText();
  const ip = state.address.split("/")[0];
  const url = `https://${state.name}.local`;
  const leak = progress.outgoing === "not_limited";
  return (
    <div className="setup-final">
      <span className="setup-final-icon" data-tone="ok" aria-hidden><Check size={22} /></span>
      <h1 id={headingId} className="setup-title setup-centred">{t.completeTitle}</h1>
      <p className="setup-lead setup-centred">{t.completeLead}</p>
      <div className="setup-stack">
        <StatusList items={items(progress, state, t)} />
        {leak && (
          <Notice icon={<CircleAlert size={16} />} tone="warning"
                  title={state.answers.network?.mode === "air-gapped" ? t.leakTitleAirGapped : t.leakTitle}>{t.leakText}</Notice>
        )}
        <div className="setup-signin">
          <p className="ui-eyebrow">{t.signInAt}</p>
          <p className="setup-signin-url">{url}</p>
          <p className="setup-detail-note">{t.orAt(`https://${ip}`)}</p>
        </div>
        <Notice icon={<Lock size={16} />} title={t.closedTitle}>{t.closedText}</Notice>
        <LinkButton href={url} className="setup-wide">{t.openSuveryn}</LinkButton>
      </div>
    </div>
  );
}
