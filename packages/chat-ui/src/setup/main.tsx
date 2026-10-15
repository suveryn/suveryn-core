// The appliance's web setup (suveryn-tracker#37, #44): its own entry and bundle, next to the chat's.
// Fonts and tokens are the chat's (bundled from suveryn-brand); nothing is loaded from the internet.
import "../styles/fonts.css";
import "../styles/tokens.css";
import "./setup.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { SetupApp } from "./SetupApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SetupApp />
  </StrictMode>,
);
