import React from "react";
import ReactDOM from "react-dom/client";
import { HarnessGui } from "../../src/App";
import LocalHostGate from "../../src/LocalHostGate";
import { initializeI18n } from "../../src/i18n";
import { createMockAppClient } from "../support/mockAppClient";

const managed = (window as unknown as { __LOUSHANG_MANAGED_TEST__?: boolean }).__LOUSHANG_MANAGED_TEST__;
void initializeI18n().then(() => ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{managed ? <LocalHostGate /> : <HarnessGui client={createMockAppClient()} />}</React.StrictMode>,
));
