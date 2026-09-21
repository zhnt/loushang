import { describe, expect, it } from "vitest";
import { projectNativeInitialSnapshot } from "../src/client/nativeLiveClient";

const identity = () => ({
  productId: "coding",
  continuityId: "continuity-1",
  sessionId: "session-1",
  scope: "cwd",
  scopeFingerprint: "a".repeat(64),
});

function nativeSnapshot() {
  return {
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
    });
    expect(snapshot.workspaces).toEqual([]);
    expect(snapshot.sessions[0].messages.map((message) => message.content)).toEqual([
      "Read the current state",
      "The state is stable.",
    ]);
    expect(snapshot.capabilities.every((capability) => capability.availability === "unavailable")).toBe(true);
  });

  it("rejects membership and service-instance mismatches", () => {
    const wrongMember = nativeSnapshot();
    wrongMember.muxSpace.members[0].session.sessionId = "other";
    expect(() => projectNativeInitialSnapshot(wrongMember)).toThrow();
    const wrongInstance = nativeSnapshot();
    wrongInstance.sessions[0].serviceInstanceId = "service-2";
    expect(() => projectNativeInitialSnapshot(wrongInstance)).toThrow();
  });
});
