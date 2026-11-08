// The appliance's web setup (suveryn-tracker#37, #44): its own entry and bundle, next to the chat's.
// Fonts and tokens are the chat's (bundled from suveryn-brand); nothing is loaded from the internet.
import "../styles/fonts.css";
import "../styles/tokens.css";
import "./setup.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PREVIEW_SCREENS, SetupApp, type PreviewScreen } from "./SetupApp";

// Development only: ?screen=5 opens that step with the demo's answers (the screen previews, src/preview/).
const asked = import.meta.env.DEV ? new URLSearchParams(location.search).get("screen") : null;
const start = PREVIEW_SCREENS.find((s) => String(s) === asked) as PreviewScreen | undefined;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SetupApp start={start} />
  </StrictMode>,
);
