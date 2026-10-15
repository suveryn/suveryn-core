/**
 * The appliance's first-boot web setup (suveryn-tracker#37; built on the component library, #44).
 * Laid out like the Keycloak login: the lockup and tagline above a 560 px card, the language menu
 * in the card's top-right corner. No sign-in and nothing from the chat: setup creates the first
 * account, so it can't depend on Keycloak.
 *
 * The spike has steps 1 (Network) and 2 (Administrator account) of 6; welcome (0) and steps 3 to 6
 * come with #37.
 */
import { Languages } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import icon from "../brand/suveryn-icon.svg";
import { Card, I18nProvider, Select, Steps } from "../ui";
import { getState, type Answers, type SetupState } from "./api";
import { Administrator } from "./steps/Administrator";
import { Network } from "./steps/Network";
import { initialLang, LANGS, LOCALES, setLang, TEXT, useLang, useText, type Lang } from "./text";

const TOTAL = 6;
type Step = 1 | 2 | "end";

export function SetupApp() {
  const t = useText();
  const language = useLang();
  const headingId = useId();
  const [state, setState] = useState<SetupState | null>(null);
  const [failed, setFailed] = useState(false);
  const [step, setStep] = useState<Step>(1);
  const [answers, setAnswers] = useState<Answers>({ network: { mode: "connected", outgoing: "approved" }, administrator: null });
  const first = useRef(true);

  useEffect(() => {
    getState().then((s) => { setLang(initialLang(s.language), false); setState(s); }, () => setFailed(true));
  }, []);

  // A new step: its title in the tab, and the focus on its heading so a screen reader starts there.
  const title = step === 1 ? t.networkTitle : step === 2 ? t.adminTitle : t.adminTitle;
  useEffect(() => { document.title = t.pageTitle(title); }, [t, title]);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const h = document.getElementById(headingId);
    if (h) { h.tabIndex = -1; h.focus(); }
    window.scrollTo({ top: 0 });
  }, [step, headingId]);

  return (
    <I18nProvider locale={LOCALES[language]}>
      <main className="setup-page">
        <div className="setup-brand">
          <div className="setup-lockup" role="img" aria-label="sūveryn">
            <img src={icon} width={44} height={44} alt="" />
            <span className="wordmark" aria-hidden>sūveryn</span>
          </div>
          <p className="setup-tagline" lang="en">{t.tagline}</p>
        </div>
        <Card className="setup-card">
          <Select
            className="setup-language"
            label={t.language}
            icon={<Languages size={16} />}
            value={language}
            onChange={(l) => setLang(l as Lang)}
            options={LANGS.map((l) => ({ id: l, label: TEXT[l].languageName, lang: l }))}
          />
          {failed ? (
            <p className="setup-lead" role="alert">{t.unreachable}</p>
          ) : !state ? (
            <p className="setup-lead" aria-busy="true">{t.loading}</p>
          ) : (
            <>
              <Steps text={t.step(step === "end" ? 3 : step, TOTAL)} step={step === "end" ? 2 : step} total={TOTAL} />
              {step === 1 && (
                <Network state={state} answers={answers.network} headingId={headingId}
                         onDone={(network) => { setAnswers((a) => ({ ...a, network })); setStep(2); }} />
              )}
              {step === 2 && (
                <Administrator applianceName={state.name} answers={answers.administrator} headingId={headingId}
                               onBack={() => setStep(1)}
                               onDone={(administrator) => { setAnswers((a) => ({ ...a, administrator })); setStep("end"); }} />
              )}
              {step === "end" && (
                <>
                  <h1 id={headingId} className="setup-title">{t.adminTitle}</h1>
                  <p className="setup-lead" data-testid="spike-end">{t.spikeEnd}</p>
                </>
              )}
            </>
          )}
        </Card>
      </main>
    </I18nProvider>
  );
}
