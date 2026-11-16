import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { InteractiveGoalViewV1 } from "../contracts/generated/bridge";
import type { HarnessClientUiPort, InteractiveGoalScope, SessionSnapshot } from "./client/model";

interface Props {
  client: HarnessClientUiPort;
  session: SessionSnapshot;
  instanceId: string;
  epoch: string | null;
  enabled: boolean;
}

export function InteractiveGoal({ client, session, instanceId, epoch, enabled }: Props) {
  const { t } = useTranslation("panels");
  const [target, setTarget] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [attempt, setAttempt] = useState<"pending" | "unknown" | "confirmed" | null>(null);
  const [observation, setObservation] = useState<{ scope: InteractiveGoalScope; view: InteractiveGoalViewV1 | null }>();
  const scope = useMemo(() => epoch === null ? null : {
    sessionId: session.id, serviceInstanceId: instanceId, connectionEpoch: epoch,
  }, [client, epoch, instanceId, session.id]);
  const current = useRef(scope);
  const pending = useRef<InteractiveGoalScope | null>(null);
  const sequence = useRef(0);

  useLayoutEffect(() => {
    current.current = scope;
    return () => { current.current = null; };
  }, [scope]);

  const readStatus = useCallback(async () => {
    if (!scope || scope !== current.current || pending.current === scope) return;
    const request = ++sequence.current;
    const view = await client.interactiveGoalStatus?.(scope).catch(() => null) ?? null;
    if (current.current === scope && sequence.current === request) {
      setObservation({ scope, view });
    }
  }, [client, scope]);

  useEffect(() => {
    void readStatus();
  }, [readStatus, session.execution?.id, session.execution?.status, session.status, session.title]);

  const view = observation?.scope === scope ? observation?.view : undefined;
  const availability = view?.availability;
  const creating = Boolean(scope && pending.current === scope);
  const unknown = attempt !== null && attempt !== "confirmed" && !creating && availability !== "present";

  useEffect(() => {
    if (availability !== "creating") return;
    const timer = window.setTimeout(() => void readStatus(), 1000);
    return () => window.clearTimeout(timer);
  }, [readStatus, observation, availability]);

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

  const created = attempt !== null && availability === "present"
    && view?.status === "active" && view.revision === 1 && !view.executionUnresolved;
  const note = creating ? t("interactiveGoal.creating")
    : created ? t("interactiveGoal.created")
    : availability === "not_ready" || availability === "creating" || availability === "historical" || availability === "cleanup_pending"
      ? t(`interactiveGoal.${availability}`)
      : view === null || !scope ? t("interactiveGoal.unavailable")
      : view === undefined ? t("interactiveGoal.loading") : null;
  return <section className="execution-detail interactive-goal" aria-label={t("interactiveGoal.title")}>
    {note && (!unknown || availability) ? <p role="status">{note}</p> : null}
    {unknown ? <p role="status">{t("interactiveGoal.unknown")}</p> : null}
    {view?.availability === "present" ? <dl>
      <dt>{t("goalProgress.goal")}</dt><dd><code>{view.goalId}</code></dd>
      <dt>{t("goalProgress.status")}</dt><dd>{t(`goalProgress.states.${view.status ?? "unknown"}`)}</dd>
      <dt>{t("interactiveGoal.revision")}</dt><dd>{view.revision}</dd>
      <dt>{t("interactiveGoal.epoch")}</dt><dd>{view.epoch}</dd>
      <dt>{t("goalProgress.unresolved")}</dt><dd>{t(view.executionUnresolved ? "goalProgress.yes" : "goalProgress.no")}</dd>
    </dl> : null}
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
    <button type="button" className="secondary-button" disabled={!scope || creating}
      onClick={() => void readStatus()}>{t("interactiveGoal.check")}</button>
  </section>;
}
