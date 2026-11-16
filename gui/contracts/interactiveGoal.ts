import type { InteractiveGoalViewV1 } from "./generated/bridge.ts";

const fields = ["availability", "goalId", "status", "revision", "epoch", "executionUnresolved"];
const unavailable = ["ready", "not_ready", "creating", "historical", "cleanup_pending"];
const statuses = ["active", "paused", "completed", "abandoned", "failed", "superseded"];

export function validateInteractiveGoal(value: unknown): InteractiveGoalViewV1 {
  const invalid = () => new Error("Invalid interactive Goal view");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const view = value as Record<string, unknown>;
  if (Object.keys(view).length !== fields.length || !fields.every((field) => Object.prototype.hasOwnProperty.call(view, field))) {
    throw invalid();
  }
  if (view.availability === "present") {
    if (typeof view.goalId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/.test(view.goalId)
      || typeof view.status !== "string" || !statuses.includes(view.status)
      || ![view.revision, view.epoch].every((count) => typeof count === "number" && Number.isSafeInteger(count) && count > 0)
      || typeof view.executionUnresolved !== "boolean") throw invalid();
  } else if (typeof view.availability !== "string" || !unavailable.includes(view.availability)
    || !fields.slice(1).every((field) => view[field] === null)) {
    throw invalid();
  }
  return value as InteractiveGoalViewV1;
}
