import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { initializeI18n } from "../src/i18n";
import { saveLayoutPreferences } from "../src/layoutPreferences";
import { afterEach, beforeEach, vi } from "vitest";

afterEach(() => cleanup());

beforeEach(async () => {
  localStorage.clear();
  // Keep navigation available to playback tests that start in an existing session.
  saveLayoutPreferences({ sidebarOpen: true });
  await initializeI18n(["en-US"]);
});

const hostPreferences = vi.hoisted(() => new Map<string, { pinned: string[]; recent: string[]; selected: string }>());
vi.mock("../src/client/hostApi", async (original) => {
  const actual = await original<typeof import("../src/client/hostApi")>();
  return { ...actual, sharedSettings: async (request: Record<string, unknown>) => {
    if (request.operation !== "preferences") return actual.sharedSettings(request);
    const scope = String(request.scope);
    const session = String(request.session ?? "");
    const value = hostPreferences.get(scope) ?? { pinned: [], recent: [], selected: "" };
    if (request.action === "visit") { value.recent = [session, ...value.recent.filter((id) => id !== session)]; value.selected = session; }
    if (request.action === "pin") value.pinned = [session, ...value.pinned.filter((id) => id !== session)];
    if (request.action === "unpin") value.pinned = value.pinned.filter((id) => id !== session);
    hostPreferences.set(scope, value);
    return structuredClone(value);
  } };
});
beforeEach(() => hostPreferences.clear());
