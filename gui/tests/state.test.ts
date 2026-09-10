import { describe, expect, it } from "vitest";
import { createMockAppClient } from "../src/client/mockAppClient";
import type { ClientEvent } from "../src/client/model";
import { emptyGuiState, guiReducer } from "../src/client/state";

describe("GUI client state", () => {
  it("keeps local Workspace, draft, activity and review choices outside remote facts", async () => {
    const snapshot = await createMockAppClient().snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot });

    expect(state.remote.workspaceOrder).toEqual([
      "workspace-loushang",
      "workspace-research",
      "workspace-scratch",
    ]);
    expect(state.local.expandedWorkspaces["workspace-loushang"]).toBe(true);

    state = guiReducer(state, { type: "workspace.toggled", workspaceId: "workspace-research" });
    state = guiReducer(state, { type: "draft.changed", sessionId: "session-gui", value: "draft for GUI" });
    state = guiReducer(state, { type: "draft.changed", sessionId: "session-ontology", value: "draft for ontology" });
    state = guiReducer(state, { type: "activity.toggled", activityGroupId: "run-gui-b1" });
    state = guiReducer(state, { type: "quick-look.opened", documentId: "document-interface-diff" });

    expect(state.local.drafts["session-gui"]).toBe("draft for GUI");
    expect(state.local.drafts["session-ontology"]).toBe("draft for ontology");
    expect(state.local.expandedWorkspaces["workspace-research"]).toBe(false);
    expect(state.local.expandedActivities["run-gui-b1"]).toBe(true);
    expect(state.local.quickLookDocumentId).toBe("document-interface-diff");
    expect(state.remote.sessions["session-gui"].context.source).toBe("fixture");
    expect(state.remote.sessions["session-gui"].run?.tasks).toHaveLength(4);
  });

  it("advances Task facts while rejecting duplicate, invalid, gapped and stale event sequences", async () => {
    const client = createMockAppClient();
    const snapshot = await client.snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot });
    const events: ClientEvent[] = [];
    client.subscribe((event) => events.push(event));

    await client.advanceFixture();
    const activity = events[events.length - 1];
    expect(activity?.type).toBe("run.activity.appended");
    state = guiReducer(state, { type: "event.received", event: activity! });
    expect(state.remote.sessions["session-gui"].run?.activities).toHaveLength(4);

    await client.advanceFixture();
    const taskUpdate = events[events.length - 1];
    state = guiReducer(state, { type: "event.received", event: taskUpdate! });
    expect(state.remote.sessions["session-gui"].run?.currentTaskId).toBe("task-model");
    expect(state.remote.sessions["session-gui"].run?.tasks[0].status).toBe("completed");

    const duplicate = guiReducer(state, { type: "event.received", event: taskUpdate! });
    expect(duplicate).toBe(state);

    const gap: ClientEvent = {
      type: "output.delta",
      id: "gap",
      generation: snapshot.generation,
      sessionId: "session-gui",
      cursor: (BigInt(taskUpdate!.cursor) + 2n).toString(),
      messageId: "message-gui-assistant-1",
      delta: "gap",
    };
    const gapState = guiReducer(state, { type: "event.received", event: gap });
    expect(gapState.remote.connection).toBe("resync-required");
    expect(gapState.diagnostic).toContain("cursor gap");

    const invalid = { ...gap, id: "invalid", cursor: "not-a-number" } as ClientEvent;
    expect(guiReducer(state, { type: "event.received", event: invalid }).diagnostic).toContain("invalid cursor");

    const stale = { ...gap, id: "stale", generation: "old-generation" } as ClientEvent;
    expect(guiReducer(state, { type: "event.received", event: stale }).diagnostic).toContain("stale generation");
  });
});
