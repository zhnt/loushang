import { describe, expect, it } from "vitest";
import { createMockAppClient } from "../src/client/mockAppClient";
import type { ClientEvent } from "../src/client/model";
import { emptyGuiState, guiReducer } from "../src/client/state";

describe("GUI client state", () => {
  it("keeps local drafts isolated while installing server facts", async () => {
    const snapshot = await createMockAppClient().snapshot();
    let state = guiReducer(emptyGuiState(), {
      type: "snapshot.installed",
      snapshot,
    });
    state = guiReducer(state, {
      type: "draft.changed",
      sessionId: "session-gui",
      value: "draft for GUI",
    });
    state = guiReducer(state, {
      type: "draft.changed",
      sessionId: "session-review",
      value: "draft for review",
    });

    expect(state.local.drafts).toEqual({
      "session-gui": "draft for GUI",
      "session-review": "draft for review",
    });
    expect(state.remote.sessions["session-gui"].context.source).toBe("fixture");
  });

  it("ignores duplicate cursors and freezes on gaps or stale generations", async () => {
    const client = createMockAppClient();
    const snapshot = await client.snapshot();
    let state = guiReducer(emptyGuiState(), {
      type: "snapshot.installed",
      snapshot,
    });
    let accepted: ClientEvent | undefined;
    client.subscribe((event) => {
      accepted = event;
    });
    await client.submitText({
      sessionId: "session-gui",
      submissionId: "state-test",
      text: "exercise cursor handling",
    });
    expect(accepted).toBeDefined();
    state = guiReducer(state, { type: "event.received", event: accepted! });

    const duplicate = guiReducer(state, {
      type: "event.received",
      event: accepted!,
    });
    expect(duplicate).toBe(state);

    const gap: ClientEvent = {
      type: "output.delta",
      id: "gap",
      generation: snapshot.generation,
      sessionId: "session-gui",
      cursor: (BigInt(accepted!.cursor) + 2n).toString(),
      messageId: "state-test:assistant",
      delta: "gap",
    };
    const gapState = guiReducer(state, { type: "event.received", event: gap });
    expect(gapState.remote.connection).toBe("resync-required");
    expect(gapState.diagnostic).toContain("cursor gap");

    const invalid: ClientEvent = { ...gap, id: "invalid", cursor: "not-a-number" };
    const invalidState = guiReducer(state, {
      type: "event.received",
      event: invalid,
    });
    expect(invalidState.remote.connection).toBe("resync-required");
    expect(invalidState.diagnostic).toContain("invalid cursor");

    const stale: ClientEvent = {
      ...gap,
      id: "stale",
      generation: "old-generation",
    };
    const staleState = guiReducer(state, {
      type: "event.received",
      event: stale,
    });
    expect(staleState.remote.connection).toBe("resync-required");
    expect(staleState.diagnostic).toContain("stale generation");
  });
});
