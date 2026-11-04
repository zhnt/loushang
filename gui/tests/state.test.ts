import { describe, expect, it } from "vitest";
import { createMockAppClient } from "../src/client/mockAppClient";
import type { ClientEvent } from "../src/client/model";
import { emptyGuiState, guiReducer } from "../src/client/state";

describe("GUI client state", () => {
  it("clears only the draft that was actually submitted", async () => {
    const snapshot = await createMockAppClient().snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot });
    state = guiReducer(state, { type: "draft.changed", sessionId: "session-gui", value: "submitted text" });
    state = guiReducer(state, { type: "draft.changed", sessionId: "session-gui", value: "edited while pending" });

    const preserved = guiReducer(state, {
      type: "draft.submitted",
      sessionId: "session-gui",
      expected: "submitted text",
    });
    expect(preserved.local.drafts["session-gui"]).toBe("edited while pending");

    const cleared = guiReducer(preserved, {
      type: "draft.submitted",
      sessionId: "session-gui",
      expected: "edited while pending",
    });
    expect(cleared.local.drafts["session-gui"]).toBe("");
  });

  it("restores Session dock choices and keeps inspected Tasks independent of progress", async () => {
    const client = createMockAppClient();
    const snapshot = await client.snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot });
    state = guiReducer(state, { type: "task.selected", taskId: "task-review" });
    client.subscribe((event) => { state = guiReducer(state, { type: "event.received", event }); });
    await client.advanceFixture();
    await client.advanceFixture();
    expect(state.remote.sessions["session-gui"].run?.currentTaskId).toBe("task-model");
    expect(state.local.selectedTaskId).toBe("task-review");
    state = guiReducer(state, { type: "session.selected", sessionId: "session-ontology" });
    expect(state.local.dockTab).toBe("environment");
    state = guiReducer(state, { type: "dock.closed" });
    state = guiReducer(state, { type: "session.selected", sessionId: "session-gui" });
    expect(state.local.dockTab).toBe("tasks");
    expect(state.local.dockOpen).toBe(true);
    expect(state.local.selectedTaskId).toBe("task-review");
    state = guiReducer(state, { type: "snapshot.installed", snapshot });
    expect(state.local.selectedTaskId).toBe("task-review");
    state = guiReducer(state, { type: "session.selected", sessionId: "session-ontology" });
    expect(state.local.dockOpen).toBe(false);
    state = guiReducer(state, { type: "snapshot.installed", snapshot: {
      ...snapshot, sessions: snapshot.sessions.map((session) => ({ ...session,
        context: { ...session.context, applicationId: "replacement-application" },
      })),
    } });
    expect(state.local.dockOpen).toBe(true);
  });

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

  it("marks only inactive Sessions unread when authoritative live snapshots advance", async () => {
    const snapshot = await createMockAppClient().snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot });
    const replacement = {
      ...snapshot,
      connection: "connected" as const,
      sessions: snapshot.sessions.map((session) => session.id === "session-ontology" ? {
        ...session,
        cursor: (BigInt(session.cursor) + 1n).toString(),
        status: "running" as const,
        execution: {
          id: "execution-ontology",
          status: "running" as const,
          revision: 1,
          interruptRequested: false,
          sourceStatus: "running" as const,
          finalCursor: null,
          truncated: false,
        },
      } : session),
    };
    state = guiReducer(state, { type: "snapshot.installed", snapshot: replacement });
    expect(state.local.selectedSessionId).toBe("session-gui");
    expect(state.local.unread["session-ontology"]).toBe(true);
    expect(state.local.unread["session-gui"]).toBe(false);
    state = guiReducer(state, { type: "session.selected", sessionId: "session-ontology" });
    expect(state.local.unread["session-ontology"]).toBe(false);
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
    const contiguous = { ...gap, cursor: (BigInt(taskUpdate!.cursor) + 1n).toString() };
    expect(guiReducer(gapState, { type: "event.received", event: contiguous })).toBe(gapState);
    const recovered = guiReducer(gapState, {
      type: "snapshot.installed",
      snapshot: { ...snapshot, sessions: snapshot.sessions.map((session) => state.remote.sessions[session.id]) },
    });
    expect(recovered.diagnostic).toBeNull();
    expect(guiReducer(recovered, { type: "event.received", event: contiguous }).remote.sessions["session-gui"].cursor).toBe(contiguous.cursor);
    const disconnected = guiReducer(state, {
      type: "snapshot.installed", snapshot: { ...snapshot, connection: "disconnected" },
    });
    expect(guiReducer(disconnected, { type: "event.received", event: activity! })).toBe(disconnected);

    const invalid = { ...gap, id: "invalid", cursor: "not-a-number" } as ClientEvent;
    expect(guiReducer(state, { type: "event.received", event: invalid }).diagnostic).toContain("invalid cursor");

    const stale = { ...gap, id: "stale", generation: "old-generation" } as ClientEvent;
    expect(guiReducer(state, { type: "event.received", event: stale }).diagnostic).toContain("stale generation");
  });
});
