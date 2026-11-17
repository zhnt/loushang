import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { InteractiveGoalReviewSubmissionV1, InteractiveGoalReviewV1 } from "../contracts/generated/bridge";
import type { HarnessClientUiPort, InteractiveGoalScope } from "./client/model";

interface Props {
  client: HarnessClientUiPort;
  reviewDiff?: (path: string) => (() => void) | undefined;
  scope: InteractiveGoalScope;
  goalId: string;
  revision: number | null;
  epoch: number | null;
  disabled: boolean;
  setReading: (reading: boolean) => void;
  submit: (input: Omit<InteractiveGoalReviewSubmissionV1, "commandId">) => void;
}

export function GoalReview({ client, scope, goalId, revision, epoch, disabled, setReading, submit, reviewDiff }: Props) {
  const { t } = useTranslation("panels");
  const [basis, setBasis] = useState<InteractiveGoalReviewV1 | null>();
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");
  const request = useRef(0);

  useLayoutEffect(() => () => { request.current++; }, [scope]);
  useLayoutEffect(() => {
    if (!loading) return;
    setReading(true);
    return () => setReading(false);
  }, [loading, setReading]);

  async function read() {
    const id = ++request.current;
    setLoading(true);
    setBasis(undefined);
    const result = await client.interactiveGoalReview?.({ ...scope, goalId }).catch(() => null);
    if (id !== request.current) return;
    setBasis(result?.goalId === goalId && result.revision === revision && result.epoch === epoch ? result : null);
    setLoading(false);
  }

  function decide(decision: InteractiveGoalReviewSubmissionV1["decision"]) {
    if (!basis || loading || disabled) return;
    submit({ goalId, reviewToken: basis.reviewToken, decision, reason: decision === "accept" ? null : reason.trim() });
    setBasis(undefined);
  }

  const validReason = reason.trim().length > 0 && new TextEncoder().encode(reason.trim()).length <= 4096;
  return <div className="goal-review">
    <button type="button" className="secondary-button" disabled={disabled || loading}
      onClick={() => void read()}>{t("interactiveGoal.review.open")}</button>
    {loading ? <p role="status">{t("interactiveGoal.review.loading")}</p> : null}
    {basis === null ? <p role="status">{t("interactiveGoal.review.unavailable")}</p> : null}
    {basis ? <div className="goal-review-summary">
      <p>{t("interactiveGoal.review.inspect")}</p>
      <details><summary>{t("interactiveGoal.review.fingerprint")}</summary><code>{basis.reviewToken}</code></details>
      {basis.changedFiles.length > 0 ? <>
        <p>{t("interactiveGoal.review.files")}</p>
        <ul>{basis.changedFiles.map((path) => {
          const open = reviewDiff?.(path);
          return <li key={path}><code>{path}</code>{open ? <button type="button" className="secondary-button"
            onClick={open}>{t("interactiveGoal.review.openDiff")}</button> : null}</li>;
        })}</ul>
      </> : <p>{t("interactiveGoal.review.noFiles")}</p>}
      {basis.filesTruncated ? <p>{t("interactiveGoal.review.truncated")}</p> : null}
      <p>{t(basis.checkCount === 0 ? "interactiveGoal.review.checksNone"
        : basis.checksSatisfied ? "interactiveGoal.review.checksPassed" : "interactiveGoal.review.checksMissing", {
        total: basis.checkCount,
      })}</p>
      <button type="button" className="secondary-button" disabled={disabled || !basis.checksSatisfied}
        onClick={() => decide("accept")}>{t("interactiveGoal.review.accept")}</button>
      <label>{t("interactiveGoal.review.reason")}
        <textarea value={reason} onChange={(event) => setReason(event.target.value)} disabled={disabled} />
      </label>
      <button type="button" className="secondary-button" disabled={disabled || !validReason}
        onClick={() => decide("reject")}>{t("interactiveGoal.review.reject")}</button>
    </div> : null}
  </div>;
}
