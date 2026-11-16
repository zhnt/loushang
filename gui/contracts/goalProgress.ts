import type { ExecutionGoalProgressV1 } from "./generated/bridge.ts";

const fields = [
  "executionId", "presence", "goalId", "status", "reasonCode", "validity",
  "executionUnresolved", "advances", "modelCalls", "batchCount",
] as const;

function identifier(value: unknown): value is string {
  return typeof value === "string" && value.length <= 128
    && /^[A-Za-z0-9]/.test(value) && !/[^A-Za-z0-9._~-]/.test(value);
}

function counter(value: unknown): boolean {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function validateGoalProgress(value: unknown, executionId: string): ExecutionGoalProgressV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== fields.length
    || fields.some((field) => !Object.prototype.hasOwnProperty.call(value, field))) {
    throw new Error("Invalid Goal progress fields");
  }
  const progress = value as Record<string, unknown>;
  if (!identifier(progress.executionId) || progress.executionId !== executionId
    || typeof progress.reasonCode !== "string" || progress.reasonCode.length > 64
    || !/^[a-z]/.test(progress.reasonCode) || /[^a-z0-9_]/.test(progress.reasonCode)
    || (progress.validity !== "not_checked" && progress.validity !== "unknown")
    || typeof progress.executionUnresolved !== "boolean"
    || ![progress.advances, progress.modelCalls, progress.batchCount].every(counter)) {
    throw new Error("Invalid Goal progress facts");
  }
  if (progress.presence === "present") {
    if (!identifier(progress.goalId) || typeof progress.status !== "string"
      || !["active", "paused", "completed", "abandoned", "failed", "superseded"].includes(progress.status)) {
      throw new Error("Invalid Goal progress identity");
    }
  } else if (!["not_started", "initializing", "unavailable"].includes(String(progress.presence))
    || typeof progress.presence !== "string" || progress.goalId !== null || progress.status !== null) {
    throw new Error("Unexpected Goal progress identity");
  }
  return value as ExecutionGoalProgressV1;
}
