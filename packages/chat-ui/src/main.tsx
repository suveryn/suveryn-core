// Fonts are bundled from src/fonts (SIL Open Font Licence); nothing is loaded from the internet.
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/app.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
