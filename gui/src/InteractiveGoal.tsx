import { type Dispatch, type SetStateAction, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { InteractiveGoalCommandV1, InteractiveGoalCommandViewV1, InteractiveGoalReviewSubmissionV1, InteractiveGoalViewV1 } from "../contracts/generated/bridge";
import type { HarnessClientUiPort, InteractiveGoalScope, SessionSnapshot } from "./client/model";

import { GoalReview } from "./GoalReview";

interface Props {
  client: HarnessClientUiPort;
  session: SessionSnapshot;
  instanceId: string;
  epoch: string | null;
  enabled: boolean;
  scopeKey: string | null;
  setBusyScope: Dispatch<SetStateAction<string | null>>;
  reviewDiff?: (path: string) => (() => void) | undefined;
}

type Action = InteractiveGoalCommandV1["action"];

function commandActive(view?: InteractiveGoalViewV1 | null): boolean {
  return view?.command?.status === "running" || view?.command?.status === "settling";
}

export function InteractiveGoal({ client, session, instanceId, epoch, enabled, scopeKey, setBusyScope, reviewDiff }: Props) {
  const { t } = useTranslation("panels");
  const [target, setTarget] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [attempt, setAttempt] = useState<"pending" | "unknown" | "confirmed" | null>(null);
  const [observation, setObservation] = useState<{
    scope: InteractiveGoalScope; view: InteractiveGoalViewV1 | null; stale?: boolean;
  }>();
  const [unconfirmed, setUnconfirmed] = useState<string>();
  const [readingReview, setReadingReview] = useState(false);
  const scope = useMemo(() => epoch === null ? null : {
    sessionId: session.id, serviceInstanceId: instanceId, connectionEpoch: epoch,
  }, [client, epoch, instanceId, session.id]);
  const current = useRef(scope);
  const pending = useRef<InteractiveGoalScope | null>(null);
  const commandPending = useRef<InteractiveGoalScope | null>(null);
  const sequence = useRef(0);

  useLayoutEffect(() => {
    current.current = scope;
    return () => { current.current = null; };
  }, [scope]);

  const readStatus = useCallback(async () => {
    if (!scope || scope !== current.current || pending.current === scope || commandPending.current === scope) return;
    const request = ++sequence.current;
    const view = await client.interactiveGoalStatus?.(scope).catch(() => null) ?? null;
    if (current.current === scope && sequence.current === request) {
      setObservation((previous) => !view && previous?.scope === scope && commandActive(previous.view)
        ? { ...previous, stale: true } : { scope, view });
      setUnconfirmed((id) => view?.command?.commandId === id ? undefined : id);
    }
  }, [client, scope]);

  useEffect(() => {
    void readStatus();
  }, [readStatus, session.execution?.id, session.execution?.status, session.status, session.title]);

  const view = observation?.scope === scope || !scope ? observation?.view : undefined;
  const lastKnown = !scope && Boolean(view);
  const availability = view?.availability;
  const creating = Boolean(scope && pending.current === scope);
  const sendingCommand = Boolean(scope && commandPending.current === scope);
  const command = view?.command;
  const running = commandActive(view);
  const busy = running || sendingCommand || readingReview;
  useLayoutEffect(() => {
    if (!scopeKey || !busy) return;
    setBusyScope(scopeKey);
    return () => setBusyScope((current) => current === scopeKey ? null : current);
  }, [busy, scopeKey, setBusyScope]);
  const unknown = attempt !== null && attempt !== "confirmed" && !creating && availability !== "present";

  useEffect(() => {
    if (!scope || sendingCommand || (availability !== "creating" && !running)) return;
    const timer = window.setTimeout(() => void readStatus(), 1500);
    return () => window.clearTimeout(timer);
  }, [readStatus, observation, availability, running, sendingCommand, scope]);

  const canCreate = Boolean(enabled && scope && availability === "ready" && !creating && !unknown);
  const validTarget = target.trim().length > 0 && new TextEncoder().encode(target).length <= 16_384;

  async function create() {
    if (!scope || scope !== current.current || pending.current === scope || !canCreate || !validTarget) return;
    pending.current = scope;
    ++sequence.current;
    setAttempt("pending");
    const result = await client.createInteractiveGoal?.({ ...scope, goalTarget: target }).catch(() => null) ?? null;
    if (pending.current === scope) pending.current = null;
    if (scope !== current.current) return;
    setObservation({ scope, view: result });
    if (result && result.availability !== "creating") {
      setAttempt(result.availability === "present" ? "confirmed" : null);
      return;
    }
    setAttempt("unknown");
    if (!result) void readStatus();
  }

  async function sendGoalCommand(
    action: InteractiveGoalCommandViewV1["action"],
    goalId: string,
    send: (scope: InteractiveGoalScope, commandId: string) => Promise<InteractiveGoalViewV1 | null> | undefined,
  ) {
    if (!scope || scope !== current.current || commandPending.current === scope || unconfirmed) return;
    const commandId = `gui-${crypto.randomUUID()}`;
    commandPending.current = scope;
    ++sequence.current;
    setUnconfirmed(commandId);
    const result = await send(scope, commandId)?.catch(() => null);
    if (commandPending.current === scope) commandPending.current = null;
    if (scope !== current.current) return;
    if (result?.goalId === goalId && result.command?.commandId === commandId && result.command.action === action) {
      setObservation({ scope, view: result });
      setUnconfirmed(undefined);
      return;
    }
    void readStatus();
  }

  function submitReview(input: Omit<InteractiveGoalReviewSubmissionV1, "commandId">) {
    void sendGoalCommand(input.decision, input.goalId, (address, commandId) =>
      client.submitInteractiveGoalReview?.({ ...address, ...input, commandId }));
  }

  const controlsDisabled = !enabled || !scope || Boolean(unconfirmed) || observation?.stale === true;
  const created = attempt !== null && availability === "present"
    && view?.status === "active" && view.revision === 1 && !view.executionUnresolved && !command && !unconfirmed;
  const note = creating ? t("interactiveGoal.creating")
    : created ? t("interactiveGoal.created")
    : availability === "not_ready" || availability === "creating" || availability === "historical" || availability === "cleanup_pending"
      ? t(`interactiveGoal.${availability}`)
      : view === null || !scope ? t("interactiveGoal.unavailable")
      : view === undefined ? t("interactiveGoal.loading") : null;
  return <section className="execution-detail interactive-goal" aria-label={t("interactiveGoal.title")}>
    {lastKnown ? <p role="status">{t("goalProgress.lastConfirmed")}</p> : null}
    {note && !lastKnown && (!unknown || availability) ? <p role="status">{note}</p> : null}
    {unknown ? <p role="status">{t("interactiveGoal.unknown")}</p> : null}
    {view?.availability === "present" ? <dl>
      <dt>{t("goalProgress.status")}</dt><dd>{t(`goalProgress.states.${view.status ?? "unknown"}`)}</dd>
    </dl> : null}
    {view?.availability === "present" && view.goalId && session.supportsInteractiveGoalCommands && client.controlInteractiveGoal ? (
      <GoalCommandControls view={view} disabled={controlsDisabled || readingReview}
        send={(action) => void sendGoalCommand(action, view.goalId!, (address, commandId) =>
          client.controlInteractiveGoal?.({ ...address, action, goalId: view.goalId!, commandId }))} />
    ) : null}
    {view?.reviewAvailable && view.goalId && scope && client.interactiveGoalReview && client.submitInteractiveGoalReview ? (
      <GoalReview key={JSON.stringify([scope.connectionEpoch, view.goalId, view.revision, view.epoch])}
        client={client} scope={scope} goalId={view.goalId} revision={view.revision} epoch={view.epoch}
        disabled={controlsDisabled} setReading={setReadingReview} submit={submitReview} reviewDiff={reviewDiff} />
    ) : null}
    {command?.action === "accept" && command.status === "finished" ? <p role="status">{t("interactiveGoal.review.accepted")}</p> : null}
    {command?.action === "reject" && command.status === "finished" ? <p role="status">{t("interactiveGoal.review.feedbackRecorded")}</p> : null}
    {(command?.action === "accept" || command?.action === "reject") && command.status === "failed" ? (
      <p role="status">{t("interactiveGoal.review.failed")}</p>
    ) : null}
    {sendingCommand ? <p role="status">{t("interactiveGoal.commands.sending")}</p>
      : unconfirmed ? <p role="status">{t("interactiveGoal.commands.unconfirmed", { id: unconfirmed })}</p> : null}
    {observation?.scope === scope && observation?.stale ? <p role="status">{t("interactiveGoal.unavailable")}</p> : null}
    {availability === "ready" && !formOpen && canCreate ? <button type="button" className="secondary-button"
      onClick={() => setFormOpen(true)}>{t("interactiveGoal.open")}</button> : null}
    {formOpen && (availability === "ready" || creating || unknown) ? <form onSubmit={(event) => {
      event.preventDefault();
      void create();
    }}>
      <label>{t("interactiveGoal.target")}
        <textarea value={target} onChange={(event) => setTarget(event.target.value)} disabled={creating || unknown} />
      </label>
      <button type="submit" className="secondary-button" disabled={!canCreate || !validTarget}>
        {t("interactiveGoal.create")}
      </button>
    </form> : null}
    {view?.availability === "present" ? <details className="goal-technical">
      <summary>{t("execution.details")}</summary>
      <dl>
        <dt>{t("goalProgress.goal")}</dt><dd><code>{view.goalId}</code></dd>
        <dt>{t("interactiveGoal.revision")}</dt><dd>{view.revision}</dd>
        <dt>{t("interactiveGoal.epoch")}</dt><dd>{view.epoch}</dd>
        <dt>{t("goalProgress.unresolved")}</dt><dd>{t(view.executionUnresolved ? "goalProgress.yes" : "goalProgress.no")}</dd>
      </dl>
    </details> : null}
    <button type="button" className="secondary-button" disabled={!scope || creating || sendingCommand}
      onClick={() => void readStatus()}>{t("interactiveGoal.check")}</button>
  </section>;
}


function GoalCommandControls({ view, disabled, send }: {
  view: InteractiveGoalViewV1;
  disabled: boolean;
  send: (action: Action) => void;
}) {
  const { t } = useTranslation("panels");
  const status = view.command?.status;
  const active = commandActive(view);
  const settled = !active && !view.executionUnresolved && status !== "unknown";
  const actions: Action[] = [];
  if (view.status === "active" && settled) actions.push("run", "step", "pause");
  if (view.status === "paused" && settled) actions.push("resume");
  if (status === "running" && view.status === "active"
    && view.command?.action !== "accept" && view.command?.action !== "reject") actions.push("pause");
  if (active && view.command?.action !== "cancel") actions.push("cancel");
  const message = status === "settling" ? (view.command?.action === "pause" ? "pausing" : "cancelling") : status;
  return <>
    {message ? <p role="status">{t(`interactiveGoal.commands.${message}`)}</p> : null}
    {actions.length ? <div className="interactive-goal-actions">
      {actions.map((action) => <button key={action} type="button" className="secondary-button"
        disabled={disabled} onClick={() => send(action)}>{t(`interactiveGoal.commands.${action}`)}</button>)}
    </div> : null}
  </>;
}
