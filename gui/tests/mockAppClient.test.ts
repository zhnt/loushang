import { describe, expect, it } from "vitest";
import { createMockAppClient } from "../src/client/mockAppClient";
import type { ClientEvent } from "../src/client/model";
import { emptyGuiState, guiReducer } from "../src/client/state";

describe("Mock AppClient snapshots", () => {
  it("recovers a missed event from current facts and accepts the following event", async () => {
    const client = createMockAppClient();
    const original = await client.snapshot();
    let state = guiReducer(emptyGuiState(), { type: "snapshot.installed", snapshot: original });
    state = guiReducer(state, { type: "draft.changed", sessionId: "session-gui", value: "Keep draft" });
    await client.advanceFixture(); // Deliberately miss one event.
    const unsubscribe = client.subscribe((event) => { state = guiReducer(state, { type: "event.received", event }); });
    await client.advanceFixture();
    expect(state.remote.connection).toBe("resync-required");
    const snapshot = await client.snapshot();
    const session = snapshot.sessions.find((item) => item.id === "session-gui")!;
    expect(session.run?.currentTaskId).toBe("task-model");
    expect(session.run?.activities).toHaveLength(4);
    expect(BigInt(session.cursor)).toBe(BigInt(original.sessions[0].cursor) + 2n);
    state = guiReducer(state, { type: "snapshot.installed", snapshot });
    expect(state.local.drafts["session-gui"]).toBe("Keep draft");
    await client.advanceFixture();
    expect(state.diagnostic).toBeNull();
    expect(state.remote.sessions["session-gui"].run?.activities).toHaveLength(5);
    // Neither the original snapshot nor a consumer-modified snapshot changes the source.
    expect(original.sessions[0].run?.currentTaskId).toBe("task-inspect");
    Object.assign(session, { title: "mutated by consumer" });
    expect((await client.snapshot()).sessions[0].title).toBe("GUI development");
    unsubscribe();
  });

  it("retains submitted, streamed and interrupted facts without subscribers", async () => {
    const client = createMockAppClient();
    await client.interrupt("session-gui");
    const receipt = await client.submitText({ sessionId: "session-ontology", submissionId: "snapshot-test", text: "Hello snapshot" });
    expect(receipt.accepted).toBe(true);
    const findSession = async () => (await client.snapshot()).sessions.find((item) => item.id === "session-ontology")!;
    expect((await findSession()).status).toBe("running");
    expect((await findSession()).messages.slice(-2)[0]?.content).toBe("Hello snapshot");
    await client.advanceFixture();
    expect((await findSession()).messages.slice(-1)[0]?.content).toContain("separate client scope");
    await client.interrupt("session-ontology");
    expect((await findSession()).status).toBe("interrupted");
    expect((await findSession()).messages.slice(-1)[0]?.phase).toBe("interrupted");
    expect(await client.advanceFixture()).toBeNull();
  });

  it("publishes isolated event copies and preserves completed facts", async () => {
    const client = createMockAppClient();
    client.subscribe((event) => { Object.assign(event, { cursor: "corrupt" }); });
    const events: ClientEvent[] = [];
    client.subscribe((event) => events.push(event));
    for (let steps = 0; steps < 30 && client.remainingFixtureSteps() > 0; steps++) await client.advanceFixture();
    const snapshot = await client.snapshot();
    expect(snapshot.sessions[0].status).toBe("idle");
    expect(snapshot.sessions[0].run?.status).toBe("completed");
    expect(snapshot.sessions[0].run?.tasks.every((task) => task.status === "completed")).toBe(true);
    expect(snapshot.sessions[0].cursor).toBe(events.slice(-1)[0]?.cursor);
    expect(events.every((event) => event.cursor !== "corrupt")).toBe(true);
  });
});
