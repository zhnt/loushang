import React from "react";
import ReactDOM from "react-dom/client";
import { initializeI18n } from "./i18n";
import App from "./App";

void initializeI18n().then(() => ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
));
