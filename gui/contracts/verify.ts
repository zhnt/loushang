// C1 candidate bridge-value validator, deliberately not wired into HarnessGUI.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function object(value: unknown, fields: string[]): Record<string, unknown> {
  assert(value !== null && typeof value === "object" && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), [...fields].sort());
  return value as Record<string, unknown>;
}
function identifier(value: unknown, max = 128) {
  assert(typeof value === "string" && value.length <= max && /^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(value));
}
function validate(kind: string, value: unknown, profile?: string) {
  if (kind === "hello") {
    const hello = object(value, ["protocolVersion", "executionVersion", "profile", "serviceInstanceId", "restartRecovery", "submissionRetention"]);
    assert.equal(hello.protocolVersion, "loushang.app/v1");
    assert.equal(hello.executionVersion, "loushang.execution/v1");
    assert.equal(hello.profile, profile);
    assert(typeof profile === "string");
    identifier(hello.serviceInstanceId);
    assert.equal(hello.restartRecovery, false);
    assert.equal(hello.submissionRetention, "service_instance_lifetime");
    return;
  }
  const root = object(value, kind === "submit"
    ? ["protocolVersion", "requestId", "operation", "payload"]
    : ["protocolVersion", "requestId", "resultType", "result"]);
  assert.equal(root.protocolVersion, "loushang.execution/v1");
  identifier(root.requestId);
  if (kind === "submit") {
    assert.equal(root.operation, "execution/submit");
    const payload = object(root.payload, ["control", "expectedInstanceId", "submissionId", "text"]);
    identifier(payload.expectedInstanceId);
    identifier(payload.submissionId);
    assert(typeof payload.text === "string" && payload.text.trim().length > 0 && [...payload.text].length <= 262_144);
    const control = object(payload.control, ["attachmentId", "memberId", "controllerGeneration"]);
    identifier(control.attachmentId, 512);
    identifier(control.memberId, 512);
    const generation = control.controllerGeneration;
    assert(typeof generation === "string" && /^[1-9][0-9]*$/.test(generation));
    assert.equal(BigInt(generation).toString(), generation);
  } else {
    assert.equal(kind, "failure");
    assert.equal(root.resultType, "failure");
    const result = object(root.result, ["code"]);
    assert(["service_instance_changed", "submission_conflict", "submission_ledger_full",
      "execution_busy", "execution_not_retained", "execution_unsupported"].includes(result.code as string));
  }
}

const lines = readFileSync(0, "utf8").trim().split("\n");
let accepted = 0;
let rejected = 0;
for (const line of lines) {
  const vector = JSON.parse(line);
  if (!vector.valid) {
    assert.equal(vector.bridge, null, vector.name);
    rejected++;
    continue;
  }
  validate(vector.kind, vector.bridge, vector.profile);
  assert.deepEqual(vector.bridge, vector.expected, vector.name);
  if (vector.kind === "hello") {
    for (const [field, value] of Object.entries({protocolVersion: "loushang.app/v2", executionVersion: "unknown", profile: "unknown/v1", restartRecovery: true, submissionRetention: "forever", serviceInstanceId: "invalid id", unexpected: true})) {
      const changed = structuredClone(vector.bridge);
      changed[field] = value;
      assert.throws(() => validate("hello", changed, vector.profile));
    }
    const missing = structuredClone(vector.bridge);
    delete missing.submissionRetention;
    assert.throws(() => validate("hello", missing, vector.profile));
    accepted++;
    continue;
  }
  const altered = structuredClone(vector.bridge);
  altered.protocolVersion = "loushang.execution/v2";
  assert.throws(() => validate(vector.kind, altered));
  delete altered.protocolVersion;
  assert.throws(() => validate(vector.kind, altered));
  if (vector.kind === "submit") {
    for (const invalid of [1, 9007199254740992, true, "01", "1e0", "0", "-1"]) {
      const lossy = structuredClone(vector.bridge);
      lossy.payload.control.controllerGeneration = invalid;
      assert.throws(() => validate(vector.kind, lossy));
    }
  } else {
    altered.protocolVersion = "loushang.execution/v1";
    altered.result.code = "unknown_error";
    assert.throws(() => validate(vector.kind, altered));
  }
  accepted++;
}
assert(accepted > 0 && rejected > 0);
console.log(`C1 submit/failure/hello probe: ${accepted} accepted, ${rejected} rejected; Python -> Rust -> TypeScript passed.`);
