import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { initializeI18n } from "../src/i18n";
import { afterEach, beforeEach } from "vitest";

afterEach(() => cleanup());

beforeEach(async () => {
  localStorage.clear();
  await initializeI18n(["en-US"]);
});
