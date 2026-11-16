import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ExecutionGoalProgressV1 } from "../contracts/generated/bridge";
import type { ExecutionProjection, HarnessClientUiPort } from "./client/model";

export function GoalProgress({ client, sessionId, execution }: {
  client: HarnessClientUiPort;
  sessionId: string;
  execution: ExecutionProjection;
}) {
  const { t } = useTranslation("panels");
  const [progress, setProgress] = useState<ExecutionGoalProgressV1 | null>(null);
  const executionId = execution.id;
  const running = execution.status === "accepted" || execution.status === "running";

  useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const observed = await client.goalProgress?.(sessionId, executionId) ?? null;
        if (!current) return;
        const progress = observed?.executionId === executionId && observed.presence !== "unavailable" ? observed : null;
        setProgress(progress);
        if (running && progress) timer = setTimeout(() => void refresh(), 2000);
      } catch {
        if (current) setProgress(null);
      }
    }
    void refresh();
    return () => { current = false; clearTimeout(timer); };
  }, [client, sessionId, executionId, running]);

  if (!progress || progress.presence === "unavailable") return null;
  return <section className="execution-detail goal-progress" aria-label={t("goalProgress.title")}>
    <strong>{t("goalProgress.title")}</strong>
    <dl>
      <dt>{t("goalProgress.goal")}</dt><dd><code>{progress.goalId ?? t("goalProgress.notObserved")}</code></dd>
      <dt>{t("goalProgress.status")}</dt><dd>{t(`goalProgress.states.${progress.presence === "present" ? progress.status ?? "unknown" : progress.presence}`)}</dd>
      <dt>{t("goalProgress.batches")}</dt><dd>{progress.batchCount}</dd>
      <dt>{t("goalProgress.models")}</dt><dd>{progress.modelCalls}</dd>
      <dt>{t("goalProgress.advances")}</dt><dd>{progress.advances}</dd>
      <dt>{t("goalProgress.reason")}</dt><dd><code>{progress.reasonCode}</code></dd>
      <dt>{t("goalProgress.validity")}</dt><dd>{t(`goalProgress.states.${progress.validity}`)}</dd>
      <dt>{t("goalProgress.unresolved")}</dt><dd>{t(progress.executionUnresolved ? "goalProgress.yes" : "goalProgress.no")}</dd>
    </dl>
  </section>;
}
