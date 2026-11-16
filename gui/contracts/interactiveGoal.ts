import type { InteractiveGoalViewV1 } from "./generated/bridge.ts";

const fields = ["availability", "goalId", "status", "revision", "epoch", "executionUnresolved"];
const unavailable = ["ready", "not_ready", "creating", "historical", "cleanup_pending"];
const identifier = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/;
const commandActions = ["run", "step", "resume", "pause", "cancel"];
const controlActions = ["pause", "cancel"];
const statuses = ["active", "paused", "completed", "abandoned", "failed", "superseded"];

function validCommand(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const { commandId, action, status } = value as Record<string, unknown>;
  if (Object.keys(value).length !== 3 || typeof commandId !== "string" || !identifier.test(commandId)
    || typeof action !== "string" || !commandActions.includes(action)) return false;
  if (status === "running") return !controlActions.includes(action);
  if (status === "settling") return controlActions.includes(action);
  return status === "finished" || status === "unknown" || status === "failed";
}

export function validateInteractiveGoal(value: unknown): InteractiveGoalViewV1 {
  const invalid = () => new Error("Invalid interactive Goal view");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const view = value as Record<string, unknown>;
  const command = Object.prototype.hasOwnProperty.call(view, "command");
  if (Object.keys(view).length !== fields.length + Number(command)
    || !fields.every((field) => Object.prototype.hasOwnProperty.call(view, field))) {
    throw invalid();
  }
  if (view.availability === "present") {
    if (typeof view.goalId !== "string" || !identifier.test(view.goalId)
      || typeof view.status !== "string" || !statuses.includes(view.status)
      || ![view.revision, view.epoch].every((count) => typeof count === "number" && Number.isSafeInteger(count) && count > 0)
      || typeof view.executionUnresolved !== "boolean" || (command && !validCommand(view.command))) throw invalid();
  } else if (typeof view.availability !== "string" || !unavailable.includes(view.availability)
    || command || !fields.slice(1).every((field) => view[field] === null)) {
    throw invalid();
  }
  return value as InteractiveGoalViewV1;
}
