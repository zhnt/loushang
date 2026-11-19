import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ExecutionProjection, SessionSnapshot } from "./client/model";

interface Props {
  session: SessionSnapshot;
  stale: boolean;
  goalControls: ReactNode;
  goalProgress: ReactNode;
  hasInteractiveGoal: boolean;
  fixtureRun?: ReactNode;
  onInterrupt?: () => void;
  interruptDisabled: boolean;
  onApproval?: () => void;
  onQuestion?: () => void;
  onConversation?: () => void;
  onReview?: () => void;
}

export function ExecutionPanel({
  session, stale, goalControls, goalProgress, hasInteractiveGoal, fixtureRun, onInterrupt, interruptDisabled,
  onApproval, onQuestion, onConversation, onReview,
}: Props) {
  const { t } = useTranslation("panels");
  const { execution } = session;
  const active = execution?.status === "accepted" || execution?.status === "running" ? execution : null;
  const recent = session.latestTerminalExecution ?? (active ? null : execution);
  const status = onApproval || onQuestion || session.status === "waiting" ? "waiting"
    : active?.status ?? (session.status === "running" ? "running" : stale && !recent ? "unknown" : "idle");

  return <>
    <section className="execution-section" aria-label={t("execution.current")}>
      <h2>{t("execution.current")}</h2>
      {(status !== "idle" || !hasInteractiveGoal) && <p className="execution-state" data-status={status} role="status">
        {t(`execution.states.${status}`)}
      </p>}
      {stale && <p className="execution-note">{t("execution.stale")}</p>}
      {onInterrupt && <button type="button" className="secondary-button" onClick={onInterrupt}
        disabled={interruptDisabled || active?.interruptRequested}>
        {t(active?.interruptRequested ? "execution.stopping" : "execution.stop")}
      </button>}
      {goalControls}
      {active && <ExecutionDetail execution={active} />}
    </section>
    {goalProgress}
    {(onApproval || onQuestion) && <section className="execution-section" aria-label={t("execution.attention")}>
      <h2>{t("execution.attention")}</h2>
      <div className="execution-actions">
        {onApproval && <button type="button" className="secondary-button" onClick={onApproval}>{t("execution.openApproval")}</button>}
        {onQuestion && <button type="button" className="secondary-button" onClick={onQuestion}>{t("execution.openQuestion")}</button>}
      </div>
    </section>}
    {recent && <section className="execution-section" aria-label={t("execution.recent")}>
      <h2>{t("execution.recent")}</h2>
      <p className="execution-state" data-status={recent.status}>{t(`execution.states.${recent.status}`)}</p>
      {(onConversation || onReview) && <div className="execution-actions">
        {onConversation && <button type="button" className="secondary-button" onClick={onConversation}>{t("execution.openConversation")}</button>}
        {onReview && <button type="button" className="secondary-button" onClick={onReview}>{t("execution.openReview")}</button>}
      </div>}
      <ExecutionDetail execution={recent} />
    </section>}
    {fixtureRun}
  </>;
}

function ExecutionDetail({ execution }: { execution: ExecutionProjection }) {
  const { t } = useTranslation("panels");
  return <details className="execution-detail">
    <summary>{t("execution.details")}</summary>
    <dl>
      <dt>{t("execution.title")}</dt><dd><code>{execution.id}</code></dd>
      <dt>{t("execution.revision")}</dt><dd>{execution.revision}</dd>
      {execution.errorCode && <><dt>{t("execution.failureCode")}</dt><dd><code>{execution.errorCode}</code></dd></>}
      <dt>{t("execution.source")}</dt><dd>{execution.sourceStatus
        ? t(`execution.states.${execution.sourceStatus}`) : t("execution.notObserved")}</dd>
      {execution.finalCursor !== null && <><dt>{t("execution.finalCursor")}</dt><dd>{execution.finalCursor}</dd></>}
      <dt>{t("execution.transcript")}</dt><dd>{t(execution.truncated ? "execution.truncated" : "execution.completeSnapshot")}</dd>
    </dl>
  </details>;
}
