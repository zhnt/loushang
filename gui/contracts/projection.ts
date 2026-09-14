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
function safeCounter(value: unknown, positive = false) {
  assert(typeof value === "number" && Number.isSafeInteger(value) && value >= (positive ? 1 : 0));
}
function terminal(status: unknown) { return ["succeeded", "failed", "interrupted"].includes(status as string); }
function observation(value: unknown) {
  const v = object(value, ["executionId", "status", "finalCursor"]);
  if (v.executionId === null) {
    assert.equal(v.status, null); assert.equal(v.finalCursor, null);
  } else {
    id(v.executionId, 128);
    assert(v.status === "running" || terminal(v.status));
    if (terminal(v.status)) safeCounter(v.finalCursor);
    else assert.equal(v.finalCursor, null);
  }
  return v;
}
function state(value: unknown) {
  const v = object(value, ["executionId", "status", "revision", "interruptRequested", "outcome"]);
  id(v.executionId, 128); safeCounter(v.revision); assert(typeof v.interruptRequested === "boolean");
  assert(["accepted", "running", "succeeded", "failed", "interrupted"].includes(v.status as string));
  if (terminal(v.status)) {
    const outcome = object(v.outcome, ["status", "errorCode", "legacyResult"]);
    assert.equal(outcome.status, v.status);
    if (v.status === "failed") id(outcome.errorCode, 128);
    else assert.equal(outcome.errorCode, null);
    const legacy = outcome.legacyResult;
    assert(legacy !== null && typeof legacy === "object" && !Array.isArray(legacy));
    if (Object.keys(legacy).length) {
      const error = object(legacy, ["code"]);
      assert(["invalid_request", "not_found", "already_exists", "already_attached", "product_mismatch", "revision_conflict", "snapshot_required", "stale_attachment", "attachment_lagged", "session_unavailable", "operation_unavailable", "cleanup_incomplete", "service_closed"].includes(error.code as string));
    }
  } else assert.equal(v.outcome, null);
  return v;
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
    const observed = observation(source.observation);
    assert(typeof source.draft === "string" && [...source.draft].length <= 16_384);
    assert(source.draft === "" || observed.status === "running");
    if (observed.finalCursor !== null) assert(BigInt(s.cursor as string) >= BigInt(observed.finalCursor as number));
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
    assert.notEqual(observation(view.quiescent).status, "running");
    if (view.active !== null) assert(!terminal(state(view.active).status));
    if (view.latestTerminal !== null) assert(terminal(state(view.latestTerminal).status));
  } else {
    assert.equal(kind, "events");
    const result = object(root.result, ["events"]);
    assert(Array.isArray(result.events) && result.events.length <= 256);
    for (const raw of result.events) {
      if (raw !== null && typeof raw === "object" && "execution" in raw) {
        const update = object(raw, ["revision", "execution"]);
        safeCounter(update.revision, true); state(update.execution);
        continue;
      }
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
