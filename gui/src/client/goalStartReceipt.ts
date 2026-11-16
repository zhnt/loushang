import type { SubmitReceipt } from "./model";

export function unknownGoalStart(submissionId: string): SubmitReceipt {
  return { submissionId, accepted: false, reason: "submission_outcome_unknown" };
}

export function goalStartReceipt(value: unknown, submissionId: string): SubmitReceipt {
  if (value === null || typeof value !== "object") throw new Error("Invalid Goal start receipt");
  const { submissionId: id, accepted, executionId, reason } = value as Partial<SubmitReceipt>;
  if (id !== submissionId) throw new Error("Mismatched Goal submission ID");
  if (accepted === true && typeof executionId === "string" && executionId) {
    return { submissionId, accepted: true, executionId };
  }
  if (accepted === false && typeof reason === "string" && reason) {
    return { submissionId, accepted: false, reason };
  }
  throw new Error("Invalid Goal start outcome");
}
