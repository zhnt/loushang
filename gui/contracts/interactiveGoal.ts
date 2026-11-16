import type { InteractiveGoalReviewV1, InteractiveGoalViewV1 } from "./generated/bridge.ts";

const fields = ["availability", "goalId", "status", "revision", "epoch", "executionUnresolved"];
const unavailable = ["ready", "not_ready", "creating", "historical", "cleanup_pending"];
const identifier = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/;
const commandActions = ["run", "step", "resume", "pause", "cancel", "accept", "reject"];
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
  const review = Object.prototype.hasOwnProperty.call(view, "reviewAvailable");
  if (Object.keys(view).length !== fields.length + Number(command) + Number(review)
    || !fields.every((field) => Object.prototype.hasOwnProperty.call(view, field))) {
    throw invalid();
  }
  if (review && (view.reviewAvailable !== true || view.availability !== "present"
    || view.status !== "paused" || view.executionUnresolved !== false
    || ["running", "settling", "unknown"].includes(String((view.command as { status?: string } | null)?.status)))) {
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


const reviewFields = ["goalId", "revision", "epoch", "reviewToken", "changedFiles", "filesTruncated", "checkCount", "checksSatisfied"];

function reviewPath(value: unknown): value is string {
  return typeof value === "string" && new TextEncoder().encode(value).length <= 1024
    && [...value].every((part) => part.charCodeAt(0) >= 32 && part.charCodeAt(0) !== 127 && part !== "\\" && part !== ":")
    && value.split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

export function validateInteractiveGoalReview(value: unknown): InteractiveGoalReviewV1 {
  const invalid = () => new Error("Invalid interactive Goal review");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const review = value as Record<string, unknown>;
  if (Object.keys(review).length !== reviewFields.length
    || !reviewFields.every((field) => Object.prototype.hasOwnProperty.call(review, field))
    || typeof review.goalId !== "string" || review.goalId.length > 128 || !identifier.test(review.goalId)
    || typeof review.reviewToken !== "string" || review.reviewToken.length !== 64 || !/^[0-9a-f]+$/.test(review.reviewToken)
    || ![review.revision, review.epoch].every((n) => typeof n === "number" && Number.isSafeInteger(n) && n > 0)
    || typeof review.checkCount !== "number" || !Number.isInteger(review.checkCount) || review.checkCount < 0 || review.checkCount > 8
    || typeof review.checksSatisfied !== "boolean" || (!review.checkCount && !review.checksSatisfied)
    || typeof review.filesTruncated !== "boolean" || !Array.isArray(review.changedFiles) || review.changedFiles.length > 100
    || !review.changedFiles.every(reviewPath) || new Set(review.changedFiles).size !== review.changedFiles.length) throw invalid();
  return value as InteractiveGoalReviewV1;
}
