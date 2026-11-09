import { expect, it } from "vitest";
import { createMockAppClient } from "./support/mockAppClient";
import type { ClientSnapshot } from "../src/client/model";
import { liveSelectionKey, rememberSessionSelection, restoreSessionSelection } from "../src/client/sessionSelection";
import { emptyGuiState, guiReducer } from "../src/client/state";
import { readSidebarPreferences, saveSidebarPreferences } from "../src/client/sidebarPreferences";

it("isolates cached navigation for matching mux IDs on different servers", () => {
  const source = { kind: "live", muxSpaceId: "same-mux", serviceInstanceId: "service", connectionEpoch: "1" } as const;
  const first = liveSelectionKey({ ...source, connectionId: "first" })!;
  const second = liveSelectionKey({ ...source, connectionId: "second" })!;
  saveSidebarPreferences(first, { pinned: ["private-session"], recent: [], selected: "private-session" });
  expect(second).not.toBe(first);
  expect(readSidebarPreferences(second)).toEqual({ pinned: [], recent: [] });
});

it("restores selection across process and service restarts within the same mux", async () => {
  const fixture = await createMockAppClient().snapshot();
  const source = { kind: "live", muxSpaceId: "mux-a", serviceInstanceId: "service-before", connectionEpoch: "1" } as const;
  const snapshot: ClientSnapshot = {
    ...fixture,
    connection: "connected",
    source,
  };
  const selected = snapshot.sessions[1].id;
  await rememberSessionSelection(liveSelectionKey(snapshot.source)!, selected);
  const restarted: ClientSnapshot = {
    ...snapshot,
    source: { ...source, serviceInstanceId: "service-after" },
  };
  const installed = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot: restoreSessionSelection(restarted) });
  expect(installed.local.selectedSessionId).toBe(selected);

  const anotherMux: ClientSnapshot = {
    ...restarted,
    source: { ...source, serviceInstanceId: "service-after", muxSpaceId: "mux-b" },
  };
  expect(guiReducer(installed, { type: "snapshot.installed", snapshot: restoreSessionSelection(anotherMux) })
    .local.selectedSessionId).toBe(snapshot.selectedSessionId);

  const missing = { ...restarted, sessions: restarted.sessions.filter((session) => session.id !== selected) };
  expect(guiReducer(installed, { type: "snapshot.installed", snapshot: restoreSessionSelection(missing) })
    .local.selectedSessionId).toBe(snapshot.selectedSessionId);
});
