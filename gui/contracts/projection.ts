import assert from "node:assert/strict";

function object(value: unknown, fields: string[]): Record<string, unknown> {
  assert(value !== null && typeof value === "object" && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), [...fields].sort());
  return value as Record<string, unknown>;
}
function id(value: unknown, max = 512) {
  assert(typeof value === "string" && value.length <= max && /^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(value));
}
function counter(value: unknown, positive = false) {
  assert(typeof value === "string" && /^(0|[1-9][0-9]*)$/.test(value));
  assert(BigInt(value) >= (positive ? 1n : 0n));
}
function identity(value: unknown) {
  const v = object(value, ["productId", "continuityId", "sessionId", "scope", "scopeFingerprint"]);
  id(v.productId, 128); id(v.continuityId); id(v.sessionId);
  assert(/^[a-z0-9][a-z0-9._-]*$/.test(v.productId as string));
  assert(["cwd", "user_home"].includes(v.scope as string));
  assert(typeof v.scopeFingerprint === "string" && /^[0-9a-f]{64}$/.test(v.scopeFingerprint));
}
function idle(value: unknown) {
  const v = object(value, ["executionId", "status", "finalCursor"]);
  assert(Object.values(v).every(value => value === null));
}
export function validateProjection(kind: string, value: unknown) {
  const root = object(value, ["protocolVersion", "requestId", "resultType", "result"]);
  assert.equal(root.protocolVersion, "loushang.execution/v1");
  assert.equal(root.resultType, kind); id(root.requestId, 128);
  if (kind === "snapshot") {
    const result = object(root.result, ["serviceInstanceId", "source", "executions"]);
    id(result.serviceInstanceId, 128);
    const source = object(result.source, ["source", "observation", "draft", "truncated"]);
    const s = object(source.source, ["identity", "title", "cursor", "revision", "running", "records"]);
    identity(s.identity); counter(s.cursor); counter(s.revision);
    assert(typeof s.title === "string" && s.title.trim() && [...s.title].length <= 256);
    assert(typeof s.running === "boolean" && typeof source.truncated === "boolean");
    idle(source.observation); assert.equal(source.draft, "");
    assert(Array.isArray(s.records) && s.records.length <= 256);
    let total = 0;
    for (const raw of s.records) {
      const record = object(raw, ["kind", "text"]);
      assert(["user", "assistant", "status", "error"].includes(record.kind as string));
      assert(typeof record.text === "string"); total += [...record.text].length;
    }
    assert(total <= 65_536);
    const view = object(result.executions, ["identity", "revision", "quiescent", "active", "latestTerminal"]);
    identity(view.identity); assert.deepEqual(view.identity, s.identity);
    assert(typeof view.revision === "number" && Number.isSafeInteger(view.revision) && view.revision >= 0);
    idle(view.quiescent); assert.equal(view.active, null); assert.equal(view.latestTerminal, null);
  } else {
    assert.equal(kind, "events");
    const result = object(root.result, ["events"]);
    assert(Array.isArray(result.events) && result.events.length <= 256);
    for (const raw of result.events) {
      const content = object(raw, ["source", "executionId"]);
      if (content.executionId !== null) id(content.executionId, 128);
      const source = object(content.source, ["sessionId", "cursor", "kind", "text", "interactionId"]);
      id(source.sessionId); counter(source.cursor, true);
      assert(["turn_started", "user_message", "assistant_delta", "assistant_message", "status", "error", "turn_completed", "turn_interrupted", "interaction_requested", "interaction_dismissed"].includes(source.kind as string));
      assert(source.text === null || (typeof source.text === "string" && [...source.text].length <= 262_144));
      if (source.interactionId !== null) id(source.interactionId);
      assert.equal(["interaction_requested", "interaction_dismissed"].includes(source.kind as string), source.interactionId !== null);
    }
  }
}
