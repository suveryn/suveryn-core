/**
 * The appliance's first-boot web setup (suveryn-tracker#37), on the component library (#44). Laid out
 * like the Keycloak login: the lockup and tagline above a 560 px card, the language menu in the card's
 * top-right corner. No sign-in and nothing from the chat: setup creates the first account, so it can't
 * depend on Keycloak.
 *
 * Screens: 0 Welcome, steps 1 to 6 (Network, Administrator, Certificate, Support, Backups, Review),
 * then Provisioning and Complete. Each step's answers are saved on the appliance on Continue (api.ts),
 * so a reload starts again at Welcome with the answers kept, or at Provisioning if it already runs.
 * Edit on the Review goes back to that step, whose Continue then returns to the Review.
 */
import { Languages } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import icon from "../brand/suveryn-icon.svg";
import { Card, I18nProvider, Select, Steps } from "../ui";
import { getState, type Progress, type SetupState } from "./api";
import { Administrator } from "./steps/Administrator";
import { Backups } from "./steps/Backups";
import { Certificate } from "./steps/Certificate";
import { Network } from "./steps/Network";
import { Complete, Provisioning } from "./steps/Provisioning";
import { Review, type Editable } from "./steps/Review";
import { Support } from "./steps/Support";
import { Welcome } from "./steps/Welcome";
import { initialLang, LANGS, LANGUAGE_NAMES, LOCALES, setLang, useLang, useText, type Lang } from "./i18n";

const TOTAL = 6;
type Screen = 0 | 1 | 2 | 3 | 4 | 5 | 6 | "provisioning" | "complete";

export function SetupApp() {
  const t = useText();
  const language = useLang();
  const headingId = useId();
  const [state, setState] = useState<SetupState | null>(null);
  const [failed, setFailed] = useState(false);
  const [screen, setScreen] = useState<Screen>(0);
  const [returnToReview, setReturnToReview] = useState(false);
  const [finished, setFinished] = useState<Progress | null>(null);
  const first = useRef(true);

  useEffect(() => {
    getState().then((s) => {
      setLang(initialLang(s.language), false);
      setState(s);
      if (s.provisioning?.state === "done") { setFinished(s.provisioning); setScreen("complete"); }
      else if (s.provisioning) setScreen("provisioning");
    }, () => setFailed(true));
  }, []);

  // A new screen: its title in the tab, and the focus on its heading so a screen reader starts there.
  const titles: Record<Screen, string> = {
    0: t.welcomeTitle, 1: t.networkTitle, 2: t.adminTitle, 3: t.certTitle, 4: t.supportTitle, 5: t.backupsTitle,
    6: t.reviewTitle, provisioning: t.provTitle, complete: t.completeTitle,
  };
  useEffect(() => { document.title = t.pageTitle(titles[screen]); });
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const h = document.getElementById(headingId);
    if (h) { h.tabIndex = -1; h.focus(); }
    window.scrollTo({ top: 0 });
  }, [screen, headingId]);

  /** A step's answers were saved: keep them in the page's copy of the state, and go on. */
  const done = (step: Exclude<Screen, 0 | 6 | "provisioning" | "complete">, answers: Partial<SetupState["answers"]>) => {
    setState((s) => s && { ...s, answers: { ...s.answers, ...answers } });
    if (returnToReview) { setReturnToReview(false); setScreen(6); } else setScreen((step + 1) as Screen);
  };
  const back = (to: Screen) => () => { setReturnToReview(false); setScreen(to); };
  const edit = (step: Editable) => { setReturnToReview(true); setScreen(step); };

  const stepProps = { headingId };
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
            options={LANGS.map((l) => ({ id: l, label: LANGUAGE_NAMES[l], lang: l }))}
          />
          {failed ? (
            <p className="setup-lead setup-no-steps" role="alert">{t.unreachable}</p>
          ) : !state ? (
            <p className="setup-lead setup-no-steps" aria-busy="true">{t.loading}</p>
          ) : (
            <>
              {typeof screen === "number" && screen > 0 && <Steps text={t.step(screen, TOTAL)} step={screen} total={TOTAL} />}
              {typeof screen !== "number" || screen === 0 ? <div className="setup-no-steps" /> : null}
              {screen === 0 && <Welcome onStart={() => setScreen(1)} {...stepProps} />}
              {screen === 1 && <Network state={state} onBack={back(0)} onDone={(network) => done(1, { network })} {...stepProps} />}
              {screen === 2 && <Administrator state={state} onBack={back(1)} onDone={(administrator) => done(2, { administrator })} {...stepProps} />}
              {screen === 3 && <Certificate state={state} onBack={back(2)} onDone={(certificate) => done(3, { certificate })} {...stepProps} />}
              {screen === 4 && <Support state={state} onBack={back(3)} onDone={(support) => done(4, { support })} {...stepProps} />}
              {screen === 5 && <Backups state={state} onBack={back(4)} onDone={(backups) => done(5, { backups })} {...stepProps} />}
              {screen === 6 && <Review state={state} onBack={back(5)} onEdit={edit} onStart={() => setScreen("provisioning")} {...stepProps} />}
              {screen === "provisioning" && (
                <Provisioning state={state} onDone={(p) => { setFinished(p); setScreen("complete"); }} {...stepProps} />
              )}
              {screen === "complete" && finished && <Complete state={state} progress={finished} {...stepProps} />}
            </>
          )}
        </Card>
      </main>
    </I18nProvider>
  );
}
