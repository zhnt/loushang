import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ExecutionGoalProgressV1 } from "../contracts/generated/bridge";
import type { ExecutionProjection, HarnessClientUiPort } from "./client/model";

export function GoalProgress({ client, sessionId, execution, connected }: {
  client: HarnessClientUiPort;
  sessionId: string;
  execution: ExecutionProjection;
  connected: boolean;
}) {
  const { t } = useTranslation("panels");
  const [observation, setObservation] = useState<{
    progress: ExecutionGoalProgressV1;
    lastConfirmed: boolean;
  } | null>(null);
  const executionId = execution.id;
  const running = execution.status === "accepted" || execution.status === "running";

  useEffect(() => {
    if (!connected) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function unavailable() {
      setObservation((previous) => previous ? { ...previous, lastConfirmed: true } : null);
    }
    async function refresh() {
      try {
        const observed = await client.goalProgress?.(sessionId, executionId) ?? null;
        if (!current) return;
        if (observed?.executionId !== executionId || observed.presence === "unavailable") {
          unavailable();
          return;
        }
        setObservation({ progress: observed, lastConfirmed: false });
        if (running) timer = setTimeout(() => void refresh(), 2000);
      } catch {
        if (current) unavailable();
      }
    }
    void refresh();
    return () => { current = false; clearTimeout(timer); };
  }, [client, sessionId, executionId, running, connected]);

  if (!observation) return null;
  const { progress, lastConfirmed } = observation;
  if (progress.presence === "unavailable") return null;
  return <section className="execution-detail goal-progress" aria-label={t("goalProgress.title")}>
    <strong>{t("goalProgress.title")}</strong>
    {(!connected || lastConfirmed) && <p className="goal-work-note" role="status">{t("goalProgress.lastConfirmed")}</p>}
    <dl>
      <dt>{t("goalProgress.status")}</dt><dd>{t(`goalProgress.states.${progress.presence === "present" ? progress.status ?? "unknown" : progress.presence}`)}</dd>
      <dt>{t("goalProgress.batches")}</dt><dd>{progress.batchCount}</dd>
      <dt>{t("goalProgress.models")}</dt><dd>{progress.modelCalls}</dd>
      <dt>{t("goalProgress.advances")}</dt><dd>{progress.advances}</dd>
    </dl>
    <GoalWorkBatches progress={progress} />
    <details className="goal-technical">
      <summary>{t("execution.details")}</summary>
      <dl>
        <dt>{t("goalProgress.goal")}</dt><dd><code>{progress.goalId ?? t("goalProgress.notObserved")}</code></dd>
        <dt>{t("goalProgress.reason")}</dt><dd><code>{progress.reasonCode}</code></dd>
        <dt>{t("goalProgress.validity")}</dt><dd>{t(`goalProgress.states.${progress.validity}`)}</dd>
        <dt>{t("goalProgress.unresolved")}</dt><dd>{t(progress.executionUnresolved ? "goalProgress.yes" : "goalProgress.no")}</dd>
      </dl>
    </details>
  </section>;
}

function GoalWorkBatches({ progress }: { progress: ExecutionGoalProgressV1 }) {
  const { t } = useTranslation("panels");
  const { batches, batchCount } = progress;
  return <details className="goal-work">
    <summary>{t("goalProgress.work.title")}</summary>
    {batchCount > batches.length && <p className="goal-work-note">
      {t("goalProgress.work.partial", { shown: batches.length, total: batchCount })}
    </p>}
    {!batches.length ? <p className="goal-work-note">{t("goalProgress.work.empty")}</p> : (
      <table aria-label={t("goalProgress.work.title")}>
        <thead><tr>
          <th scope="col">{t("goalProgress.work.batch")}</th>
          <th scope="col">{t("goalProgress.work.status")}</th>
          <th scope="col">{t("goalProgress.work.recording")}</th>
          <th scope="col">{t("goalProgress.work.cancellation")}</th>
        </tr></thead>
        <tbody>{batches.map((batch) => <tr key={batch.batchId}>
          <th scope="row">
            <code title={batch.batchId}>{batch.batchId}</code>
            {batch.observationUnavailable && <small>{t("goalProgress.work.unavailable")}</small>}
          </th>
          <td>{batch.workStatus === null ? t("goalProgress.work.notObserved") : t(`goalProgress.work.states.${batch.workStatus}`)}</td>
          <td>{t(batch.recordingAvailable ? "goalProgress.work.observable" : "goalProgress.work.recordingUnavailable")}</td>
          <td>{batch.cancellationStatus === null ? t("goalProgress.work.notObserved")
            : t(`goalProgress.work.cancellationStates.${batch.cancellationStatus}`)}</td>
        </tr>)}</tbody>
      </table>
    )}
  </details>;
}
