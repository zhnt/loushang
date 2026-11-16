import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { unknownGoalStart } from "./client/goalStartReceipt";
import type { ClientSource, HarnessClientUiPort, SessionSnapshot, SubmitReceipt } from "./client/model";

type Attempt =
  | { submissionId: string; status: "pending" | "accepted" | "unknown" }
  | { submissionId: string; status: "rejected"; reason: string };

type LiveSource = Extract<ClientSource, { kind: "live" }>;

function assessStart(submissionId: string, receipt: SubmitReceipt): Attempt {
  if (receipt.submissionId !== submissionId) return { submissionId, status: "unknown" };
  if (receipt.accepted && receipt.executionId) return { submissionId, status: "accepted" };
  if (receipt.accepted || !receipt.reason || receipt.reason === "submission_outcome_unknown") {
    return { submissionId, status: "unknown" };
  }
  return { submissionId, status: "rejected", reason: receipt.reason };
}

export function useGoalStart(
  client: HarnessClientUiPort,
  session: SessionSnapshot | undefined,
  source: LiveSource | null,
  controlsAllowed: boolean,
) {
  const [attempts, setAttempts] = useState<Readonly<Record<string, Attempt>>>({});
  const locked = useRef(new Set<string>());
  // A Host snapshot supersedes UI receipt state, including after a reconnect.
  if (!source || !session || session.execution) return {};
  const { serviceInstanceId, connectionId } = source;
  const key = JSON.stringify([connectionId, serviceInstanceId, session.id]);
  const attempt = attempts[key];
  const canStart = controlsAllowed && session.supportsGoalStart && session.status !== "running";

  async function submit(sessionId: string) {
    if (locked.current.has(key) || !client.startGoal) return;
    const submissionId = `gui-${crypto.randomUUID()}`;
    locked.current.add(key);
    const publish = (next: Attempt) => setAttempts((current) => ({ ...current, [key]: next }));
    publish({ submissionId, status: "pending" });

    const receipt = await client.startGoal({ sessionId, submissionId }, serviceInstanceId)
      .catch(() => unknownGoalStart(submissionId));
    const outcome = assessStart(submissionId, receipt);
    publish(outcome);
    if (outcome.status === "rejected") locked.current.delete(key);
  }

  return {
    attempt,
    start: canStart && client.startGoal && (!attempt || attempt.status === "rejected")
      ? () => void submit(session.id) : undefined,
  };
}

export function GoalStart({ attempt, start }: { attempt?: Attempt; start?: () => void }) {
  const { t } = useTranslation("panels");
  if (!attempt && !start) return null;
  return <section className="execution-detail goal-start" aria-label={t("goalStart.label")}>
    {attempt ? <p role="status">
      {t(`goalStart.${attempt.status}`)}
      {attempt.status === "rejected" ? <> <code>{attempt.reason}</code></> : null}
    </p> : null}
    {start || attempt?.status === "pending" ? <button type="button" className="secondary-button"
      onClick={start} disabled={!start}>{t("goalStart.label")}</button> : null}
  </section>;
}
