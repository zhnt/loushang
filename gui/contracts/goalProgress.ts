import type { ExecutionGoalProgressV1 } from "./generated/bridge.ts";

const maxBatches = 16;
const fields = [
  "executionId", "presence", "goalId", "status", "reasonCode", "validity",
  "executionUnresolved", "advances", "modelCalls", "batchCount", "batches",
] as const;
const batchFields = [
  "batchId", "workStatus", "recordingAvailable", "cancellationStatus", "observationUnavailable",
] as const;

function closedObject(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== fields.length
    || fields.some((field) => !Object.prototype.hasOwnProperty.call(value, field))) {
    throw new Error("Invalid Goal observation fields");
  }
  return value as Record<string, unknown>;
}

function identifier(value: unknown): value is string {
  return typeof value === "string" && value.length <= 128
    && /^[A-Za-z0-9]/.test(value) && !/[^A-Za-z0-9._~-]/.test(value);
}

function counter(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function oneOf(value: unknown, choices: readonly string[]): boolean {
  return typeof value === "string" && choices.includes(value);
}

function validateBatches(value: unknown, count: number): void {
  if (!Array.isArray(value) || value.length !== Math.min(count, maxBatches)) {
    throw new Error("Invalid Goal batch count");
  }
  const ids = new Set<string>();
  for (const row of value) {
    const batch = closedObject(row, batchFields);
    if (!identifier(batch.batchId) || ids.has(batch.batchId)
      || typeof batch.recordingAvailable !== "boolean" || typeof batch.observationUnavailable !== "boolean"
      || (batch.workStatus !== null
        && !oneOf(batch.workStatus, ["accepted", "running", "cancelling", "completed", "failed", "cancelled", "orphaned"]))
      || (batch.cancellationStatus !== null
        && !oneOf(batch.cancellationStatus, ["not_requested", "pending", "settled", "unsupported", "failed", "unknown"]))) {
      throw new Error("Invalid Goal batch observation");
    }
    ids.add(batch.batchId);
  }
}

export function validateGoalProgress(value: unknown, executionId: string): ExecutionGoalProgressV1 {
  const progress = closedObject(value, fields);
  if (!identifier(progress.executionId) || progress.executionId !== executionId
    || typeof progress.reasonCode !== "string" || progress.reasonCode.length > 64
    || !/^[a-z]/.test(progress.reasonCode) || /[^a-z0-9_]/.test(progress.reasonCode)
    || !oneOf(progress.validity, ["not_checked", "unknown"])
    || typeof progress.executionUnresolved !== "boolean"
    || !counter(progress.batchCount) || !counter(progress.advances) || !counter(progress.modelCalls)) {
    throw new Error("Invalid Goal progress facts");
  }
  if (progress.presence === "present") {
    if (!identifier(progress.goalId)
      || !oneOf(progress.status, ["active", "paused", "completed", "abandoned", "failed", "superseded"])) {
      throw new Error("Invalid Goal progress identity");
    }
  } else if (!oneOf(progress.presence, ["not_started", "initializing", "unavailable"])
    || progress.goalId !== null || progress.status !== null) {
    throw new Error("Unexpected Goal progress identity");
  }
  validateBatches(progress.batches, progress.batchCount);
  return value as ExecutionGoalProgressV1;
}
