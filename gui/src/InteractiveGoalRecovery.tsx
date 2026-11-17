import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { InteractiveGoalRecoveryV1 } from "../contracts/generated/bridge";
import type { HarnessClientUiPort } from "./client/model";

interface Props {
  client: HarnessClientUiPort;
  sessionId: string;
  instanceId: string;
  epoch: string | null;
}

export function InteractiveGoalRecovery({ client, sessionId, instanceId, epoch }: Props) {
  const { t } = useTranslation("panels");
  const [observed, setObserved] = useState<{ epoch: string; recovery: InteractiveGoalRecoveryV1 | null }>();
  useEffect(() => {
    if (epoch === null) return;
    let current = true;
    void client.interactiveGoalRecovery?.({
      sessionId, serviceInstanceId: instanceId, connectionEpoch: epoch,
    }).then((recovery) => {
      if (current) setObserved({ epoch, recovery });
    }).catch(() => {
      if (current) setObserved({ epoch, recovery: null });
    });
    return () => { current = false; };
  }, [client, sessionId, instanceId, epoch]);

  const recovery = observed?.epoch === epoch ? observed?.recovery : undefined;
  if (!epoch || recovery?.presence === "absent") return null;
  return <section className="execution-detail interactive-goal" aria-label={t("interactiveGoal.recovery.title")}>
    <p>{t("interactiveGoal.recovery.readOnly")}</p>
    {recovery?.presence === "present" ? <dl>
      <dt>{t("goalProgress.status")}</dt><dd>{recovery.goalStatus === "active"
        ? t("interactiveGoal.recovery.active") : t(`goalProgress.states.${recovery.goalStatus ?? "unknown"}`)}</dd>
      <dt>{t("interactiveGoal.recovery.batches")}</dt><dd>{recovery.batchCount}</dd>
      <dt>{t("interactiveGoal.recovery.completed")}</dt><dd>{recovery.completedCount}</dd>
      <dt>{t("interactiveGoal.recovery.failed")}</dt><dd>{recovery.failedCount}</dd>
      <dt>{t("interactiveGoal.recovery.cancelled")}</dt><dd>{recovery.cancelledCount}</dd>
      <dt>{t("interactiveGoal.recovery.orphaned")}</dt><dd>{recovery.orphanedCount}</dd>
    </dl> : <p role="status">{recovery === undefined
      ? t("interactiveGoal.recovery.loading") : t("interactiveGoal.recovery.unavailable")}
      {recovery?.reasonCode ? <> <code>{recovery.reasonCode}</code></> : null}</p>}
    {recovery?.presence === "present" ? <details className="goal-technical">
      <summary>{t("execution.details")}</summary>
      <dl>
        <dt>{t("goalProgress.goal")}</dt><dd><code>{recovery.goalId}</code></dd>
        <dt>{t("interactiveGoal.recovery.reason")}</dt><dd><code>{recovery.reasonCode}</code></dd>
        <dt>{t("interactiveGoal.revision")}</dt><dd>{recovery.revision}</dd>
        <dt>{t("interactiveGoal.epoch")}</dt><dd>{recovery.epoch}</dd>
      </dl>
    </details> : null}
    {recovery?.executionUnresolved ? <p role="status">{t("interactiveGoal.recovery.unresolved")}</p> : null}
  </section>;
}
