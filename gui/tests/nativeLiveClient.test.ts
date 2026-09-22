import { describe, expect, it } from "vitest";
import { projectNativeEventRound, projectNativeInitialSnapshot } from "../src/client/nativeLiveClient";

const identity = () => ({
  productId: "coding",
  continuityId: "continuity-1",
  sessionId: "session-1",
  scope: "cwd",
  scopeFingerprint: "a".repeat(64),
});

function nativeSnapshot(): any {
  return {
    connectionEpoch: "1",
    serviceInstanceId: "service-1",
    muxSpace: {
      muxSpaceId: "mux-1",
      name: "GUI work",
      revision: "9007199254740993",
      members: [{ memberId: "member-1", session: identity(), title: "Session", position: "1" }],
    },
    sessions: [{
      serviceInstanceId: "service-1",
      source: {
        source: {
          identity: identity(),
          title: "Live session",
          cursor: "9007199254741000",
          revision: "7",
          running: false,
          records: [
            { kind: "user", text: "Read the current state" },
            { kind: "assistant", text: "The state is stable." },
          ],
        },
        observation: { executionId: null, status: null, finalCursor: null },
        draft: "",
        truncated: false,
      },
      executions: {
        identity: identity(),
        revision: 0,
        quiescent: { executionId: null, status: null, finalCursor: null },
        active: null,
        latestTerminal: null,
      },
    }],
  };
}

describe("native live initial snapshot", () => {
  it("projects a lossless read-only snapshot without fixture or repository facts", () => {
    const snapshot = projectNativeInitialSnapshot(nativeSnapshot());
    expect(snapshot.generation).toBe("9007199254740993");
    expect(snapshot.source).toEqual({
      kind: "live",
      serviceInstanceId: "service-1",
      muxSpaceId: "mux-1",
      connectionEpoch: "1",
    });
    expect(snapshot.workspaces).toEqual([]);
    expect(snapshot.sessions[0].messages.map((message) => message.content)).toEqual([
      "Read the current state",
      "The state is stable.",
    ]);
    expect(snapshot.capabilities.every((capability) => capability.availability === "unavailable")).toBe(true);
  });

  it("installs a complete validated event round from its authoritative snapshots", () => {
    const initial = nativeSnapshot();
    const next = nativeSnapshot();
    next.sessions[0].source.source.cursor = "9007199254741001";
    next.sessions[0].source.source.records.push({ kind: "assistant", text: "A later event." });
    const projected = projectNativeEventRound(initial, {
      connectionEpoch: "1",
      sequence: "1",
      serviceInstanceId: "service-1",
      muxSpaceId: "mux-1",
      members: [{
        memberId: "member-1",
        sessionId: "session-1",
        events: [{
          source: {
            sessionId: "session-1",
            cursor: "9007199254741001",
            kind: "assistant_message",
            text: "A later event.",
            interactionId: null,
          },
          executionId: "execution-1",
        }],
      }],
      sessions: next.sessions,
    });
    expect(projected.sessions[0].cursor).toBe("9007199254741001");
    expect(projected.sessions[0].messages[2]?.content).toBe("A later event.");
  });

  it("projects streaming draft and terminal execution facts without inventing Tasks", () => {
    const streaming = nativeSnapshot();
    streaming.sessions[0].source.source.running = true;
    streaming.sessions[0].source.observation = {
      executionId: "execution-1", status: "running", finalCursor: null,
    };
    streaming.sessions[0].source.draft = "A partial answer";
    streaming.sessions[0].executions.revision = 1;
    streaming.sessions[0].executions.active = {
      executionId: "execution-1",
      status: "running",
      revision: 1,
      interruptRequested: false,
      outcome: null,
    };
    const active = projectNativeInitialSnapshot(streaming);
    expect(active.sessions[0].status).toBe("running");
    expect(active.sessions[0].messages[active.sessions[0].messages.length - 1]).toMatchObject({
      content: "A partial answer", phase: "streaming",
    });
    expect(active.sessions[0].execution).toMatchObject({
      id: "execution-1", status: "running", revision: 1,
    });
    expect(active.sessions[0].run).toBeNull();
    expect(active.capabilities.find((item) => item.name === "tasks")?.availability).toBe("unavailable");

    const completed = structuredClone(streaming);
    completed.sessions[0].source.source.running = false;
    completed.sessions[0].source.source.cursor = "9007199254741001";
    completed.sessions[0].source.source.records.push({ kind: "assistant", text: "A final answer" });
    completed.sessions[0].source.observation = {
      executionId: "execution-1", status: "succeeded", finalCursor: 42,
    };
    completed.sessions[0].source.draft = "";
    completed.sessions[0].executions.revision = 2;
    completed.sessions[0].executions.active = null;
    completed.sessions[0].executions.latestTerminal = {
      executionId: "execution-1",
      status: "succeeded",
      revision: 2,
      interruptRequested: false,
      outcome: { status: "succeeded", errorCode: null, legacyResult: {} },
    };
    const final = projectNativeEventRound(streaming, {
      connectionEpoch: "1",
      sequence: "1",
      serviceInstanceId: "service-1",
      muxSpaceId: "mux-1",
      members: [{
        memberId: "member-1",
        sessionId: "session-1",
        events: [{
          source: {
            sessionId: "session-1",
            cursor: "9007199254741001",
            kind: "assistant_message",
            text: "A final answer",
            interactionId: null,
          },
          executionId: "execution-1",
        }, {
          revision: 2,
          execution: completed.sessions[0].executions.latestTerminal,
        }],
      }],
      sessions: completed.sessions,
    });
    expect(final.sessions[0].status).toBe("idle");
    expect(final.sessions[0].messages[final.sessions[0].messages.length - 1]).toMatchObject({
      content: "A final answer", phase: "complete",
    });
    expect(final.sessions[0].messages.some((message) => message.phase === "streaming")).toBe(false);
    expect(final.sessions[0].execution).toMatchObject({ status: "succeeded", revision: 2 });
  });

  it("rejects a round gap before publishing its replacement snapshot", () => {
    const initial = nativeSnapshot();
    expect(() => projectNativeEventRound(initial, {
      connectionEpoch: "1",
      sequence: "2",
      serviceInstanceId: "service-1",
      muxSpaceId: "mux-1",
      members: [{ memberId: "member-1", sessionId: "session-1", events: [] }],
      sessions: initial.sessions,
    })).toThrow();
  });

  it("rejects membership and service-instance mismatches", () => {
    const wrongMember = nativeSnapshot();
    wrongMember.muxSpace.members[0].session.sessionId = "other";
    expect(() => projectNativeInitialSnapshot(wrongMember)).toThrow();
    const wrongInstance = nativeSnapshot();
    wrongInstance.sessions[0].serviceInstanceId = "service-2";
    expect(() => projectNativeInitialSnapshot(wrongInstance)).toThrow();
  });

  it("updates one member of a two-Session round without changing the other", () => {
    const initial = nativeSnapshot();
    const secondIdentity = {
      ...identity(), continuityId: "continuity-2", sessionId: "session-2",
    };
    const second = structuredClone(initial.sessions[0]);
    second.source.source.identity = secondIdentity;
    second.source.source.title = "Second live session";
    second.source.source.cursor = "11";
    second.source.source.records = [{ kind: "user", text: "Second prompt" }];
    second.executions.identity = secondIdentity;
    initial.muxSpace.members.push({
      memberId: "member-2", session: secondIdentity, title: "Second", position: "2",
    });
    initial.sessions.push(second);
    const next = structuredClone(initial);
    next.sessions[1].source.source.cursor = "12";
    next.sessions[1].source.source.records.push({ kind: "assistant", text: "Second answer" });
    const projected = projectNativeEventRound(initial, {
      connectionEpoch: "1",
      sequence: "1",
      serviceInstanceId: "service-1",
      muxSpaceId: "mux-1",
      members: [{ memberId: "member-1", sessionId: "session-1", events: [] }, {
        memberId: "member-2",
        sessionId: "session-2",
        events: [{
          source: {
            sessionId: "session-2", cursor: "12", kind: "assistant_message",
            text: "Second answer", interactionId: null,
          },
          executionId: null,
        }],
      }],
      sessions: next.sessions,
    });
    expect(projected.sessions).toHaveLength(2);
    expect(projected.sessions[0].messages).toHaveLength(2);
    expect(projected.sessions[1].messages[projected.sessions[1].messages.length - 1].content).toBe("Second answer");
  });

  it("rejects malformed transcript and execution projections", () => {
    const malformedRecord = nativeSnapshot();
    malformedRecord.sessions[0].source.source.records[0] = { kind: "unknown", text: "bad" };
    expect(() => projectNativeInitialSnapshot(malformedRecord)).toThrow();
    const malformedExecution = nativeSnapshot();
    malformedExecution.sessions[0].executions.active = {
      executionId: "execution-1",
      status: "succeeded",
      revision: 1,
      interruptRequested: false,
      outcome: null,
    };
    expect(() => projectNativeInitialSnapshot(malformedExecution)).toThrow();
  });
});
