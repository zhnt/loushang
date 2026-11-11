const identity = () => ({
  productId: "coding",
  continuityId: "continuity-1",
  sessionId: "session-1",
  scope: "cwd",
  scopeFingerprint: "a".repeat(64),
});

export function liveSnapshot(): any {
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

