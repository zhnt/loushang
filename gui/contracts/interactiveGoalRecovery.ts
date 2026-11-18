import type { InteractiveGoalRecoveryV1 } from "./generated/bridge.ts";

const counts = ["batchCount", "completedCount", "failedCount", "cancelledCount", "orphanedCount"];
const identity = ["goalId", "goalStatus", "revision", "epoch"];
const fields = ["presence", "reasonCode", "executionUnresolved", "readOnly", ...identity, ...counts];
const statuses = ["active", "paused", "completed", "abandoned", "failed", "superseded"];
const reasons = [
  "created", "review_required", "requirements_satisfied", "user_accepted_current_result", "user_pause", "user_resume",
  "user_review", "user_cancel", "run_interrupted", "batch_limit", "execution_unresolved", "other",
];
const unavailable = ["source_changed", "goal_journal_invalid", "work_log_invalid", "unsupported_goal", "ambiguous_goal"];

function counter(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function validateInteractiveGoalRecovery(value: unknown): InteractiveGoalRecoveryV1 {
  const fail = () => new Error("Invalid Goal recovery");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw fail();
  const record = value as Record<string, unknown>;
  if (Object.keys(record).length !== fields.length || !fields.every((field) => Object.prototype.hasOwnProperty.call(record, field))
    || record.readOnly !== true || typeof record.executionUnresolved !== "boolean"
    || typeof record.reasonCode !== "string") throw fail();
  const work = counts.map((field) => record[field]);
  if (!work.every(counter) || work.slice(1).reduce((sum, n) => sum + n, 0) > work[0]
    || (work[4] > 0 && !record.executionUnresolved)) throw fail();
  if (record.presence === "present") {
    if (typeof record.goalId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/.test(record.goalId)
      || typeof record.goalStatus !== "string" || !statuses.includes(record.goalStatus)
      || ![record.revision, record.epoch].every((n) => counter(n) && n > 0)
      || !reasons.includes(record.reasonCode)) throw fail();
  } else {
    if (!identity.every((field) => record[field] === null) || work[0] !== 0) throw fail();
    const absent = record.presence === "absent" && record.reasonCode === "no_goal" && !record.executionUnresolved;
    const unknown = record.presence === "unavailable" && unavailable.includes(record.reasonCode) && record.executionUnresolved;
    if (!absent && !unknown) throw fail();
  }
  return value as InteractiveGoalRecoveryV1;
}
