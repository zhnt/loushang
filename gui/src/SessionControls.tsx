import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { UiIcon } from "./UiIcon";
import type {
  PendingSessionMutation, SessionCommandData, SessionMutation, SessionOperationPort,
  SessionOperationReply, SessionOperationScope,
} from "./client/sessionOperations";

export type SessionControlsPage = "info" | "tools";
type ExecutionState = NonNullable<NonNullable<SessionOperationReply>["state"]>;
type Feedback = { kind: "succeeded" | "interrupted" | "failed"; reason?: string };

interface Props {
  page: SessionControlsPage;
  scope: SessionOperationScope;
  request: SessionOperationPort;
  pending: Map<string, PendingSessionMutation>;
  pendingKey: string;
  executionKey?: string;
  canMutate: boolean;
  onClose: () => void;
}

export function SessionControls({
  page, scope, request, pending, pendingKey, executionKey, canMutate, onClose,
}: Props) {
  const { t, i18n } = useTranslation("session");
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(false);
  const { sessionId, serviceInstanceId, connectionEpoch } = scope;
  const [revision, setRevision] = useState(0);
  const [read, setRead] = useState<{ revision: number; executionKey?: string; data?: SessionCommandData; error?: string }>();
  const [checking, setChecking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [interrupting, setInterrupting] = useState(false);
  const [execution, setExecution] = useState<ExecutionState>();
  const [feedback, setFeedback] = useState<Feedback>();
  const operation = pending.get(pendingKey);
  const refresh = () => setRevision((value) => value + 1);

  useLayoutEffect(() => {
    const node = dialog.current;
    mounted.current = true;
    if (node && !node.open) node.showModal();
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    void request({ sessionId, serviceInstanceId, connectionEpoch }, { action: page }).then((result) => {
      if (!active) return;
      const data = result?.data;
      const session = data?.session;
      const tools = data?.available_tools;
      const valid = data?.status === "ok" && (page === "info"
        ? session?.session_id === sessionId
          && (session.session_name == null || typeof session.session_name === "string")
          && Number.isSafeInteger(session.active_tool_count)
        : Array.isArray(tools) && tools.every((tool) => tool && typeof tool.name === "string"
          && typeof tool.active === "boolean"
          && (tool.description == null || typeof tool.description === "string")));
      setRead(valid ? { revision, executionKey, data } : {
        revision, executionKey, error: result?.error ?? data?.message ?? (data?.truncated ? "truncated" : "operation_unavailable"),
      });
    }).catch(() => {
      if (active) setRead({ revision, executionKey, error: "connection_failed" });
    });
    return () => { active = false; };
  }, [request, page, sessionId, serviceInstanceId, connectionEpoch, revision, executionKey]);

  useEffect(() => {
    if (!operation || submitting) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const lookup = async () => {
      setChecking(true);
      try {
        const reply = await request({ sessionId, serviceInstanceId, connectionEpoch }, {
          action: "lookup", submissionId: operation.id,
        });
        if (!active || pending.get(pendingKey) !== operation) return;
        const state = reply?.state;
        setExecution(state);
        if (!state) return;
        if (state.status === "running" || state.status === "accepted") {
          timer = setTimeout(() => void lookup(), 800);
          return;
        }
        pending.delete(pendingKey);
        const reason = state.status === "failed"
          ? reply?.data?.message ?? state.outcome?.errorCode ?? "operation_unavailable"
          : undefined;
        setFeedback({ kind: state.status, reason });
        setRevision((value) => value + 1);
      } catch {
        if (active) setExecution(undefined);
      } finally {
        if (active) setChecking(false);
      }
    };
    void lookup();
    return () => { active = false; clearTimeout(timer); };
  }, [operation, pending, pendingKey, request, sessionId, serviceInstanceId, connectionEpoch, submitting, revision]);

  async function mutate(mutation: SessionMutation) {
    if (!canMutate || pending.has(pendingKey)) return;
    const id = crypto.randomUUID();
    const receipt = { action: mutation.action, id };
    pending.set(pendingKey, receipt);
    setSubmitting(true);
    setExecution(undefined);
    setFeedback(undefined);
    try {
      const response = await request(scope, { ...mutation, submissionId: id });
      if (response?.error && response.error !== "submission_conflict") {
        if (pending.get(pendingKey) === receipt) pending.delete(pendingKey);
        if (mounted.current) {
          setFeedback({ kind: "failed", reason: response.error });
          refresh();
        }
      }
    } catch {
      // The command could have been accepted. Recovery uses the original ID.
    } finally {
      if (mounted.current) setSubmitting(false);
    }
  }

  async function interrupt(executionId: string) {
    setInterrupting(true);
    try {
      const response = await request(scope, { action: "interrupt", executionId });
      if (mounted.current && response?.error) setFeedback({ kind: "failed", reason: response.error });
    } catch {
      // The next lookup will show whether the interrupt took effect.
    } finally {
      if (mounted.current) {
        setInterrupting(false);
        refresh();
      }
    }
  }

  const currentRead = read?.revision === revision && read.executionKey === executionKey ? read : undefined;
  const { data, error } = currentRead ?? {};
  const info = data?.session;
  const context = info?.context;
  const compaction = info?.compaction;
  const format = new Intl.NumberFormat(i18n.resolvedLanguage);
  const formattedTokens = (tokens: number) => format.format(tokens);
  const estimate = context?.accuracy === "estimated" || context?.accuracy === "projected"
    || ["logical_mismatch", "unavailable"].includes(context?.structural_envelope_status ?? "");
  const canApply = canMutate && !operation && Boolean(data);
  const title = t(page === "tools" ? "sessionControls.tools" : "sessionControls.info");
  const pendingLabel = operation?.action === "compact"
    ? t("sessionControls.compact") : t("sessionControls.tools");

  return <dialog ref={dialog} className="frame-dialog session-controls" aria-label={title}
    onClose={onClose} onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header>
      <h2>{title}</h2>
      <button className="icon-close" type="button" aria-label={t("sessionControls.close")} onClick={onClose}>
        <UiIcon name="close" />
      </button>
    </header>
    {error ? <p role="alert">{t("sessionControls.readFailed", { reason: error })}</p> : null}
    {!data && !error ? <p role="status">{t("sessionControls.loading")}</p> : null}
    {page === "tools" && data ? <>
      <p className="session-controls-hint">{t("sessionControls.toolsHint")}</p>
      <ul className="session-tool-list">
        {data.available_tools?.map((tool) => <li key={tool.name}>
          <label>
            <input type="checkbox" checked={tool.active} disabled={!canApply || tool.allowed !== true}
              onChange={(event) => void mutate({ action: "setTool", name: tool.name, active: event.target.checked })} />
            <span><strong>{tool.name}</strong><small>
              {t(tool.allowed === true ? "sessionControls.allowed" : tool.allowed === false
                ? "sessionControls.denied" : "sessionControls.unknownPermission")}
            </small>{tool.description ? <span className="session-tool-description">{tool.description}</span> : null}</span>
          </label>
        </li>)}
      </ul>
      {!data.available_tools?.length ? <p>{t("sessionControls.noTools")}</p> : null}
      <button className="secondary-button" type="button" disabled={!canApply}
        onClick={() => void mutate({ action: "resetTools" })}>{t("sessionControls.reset")}</button>
    </> : null}
    {page === "info" && info ? <>
      <dl>
        {info.session_name ? <><dt>{t("sessionControls.name")}</dt><dd>{info.session_name}</dd></> : null}
        <dt>{t("sessionControls.identity")}</dt><dd><code>{info.session_id}</code></dd>
        {typeof context?.tokens === "number" ? <>
          <dt>{t("sessionControls.context")}</dt>
          <dd>{estimate ? "≈" : ""}{formattedTokens(context.tokens)}
            {typeof context.context_window === "number" ? ` / ${formattedTokens(context.context_window)}` : ""}</dd>
        </> : null}
        <dt>{t("sessionControls.activeTools")}</dt><dd>{info.active_tool_count}</dd>
        {info.is_compacting ? <><dt>{t("sessionControls.compaction")}</dt><dd>{t("sessionControls.running")}</dd></> : null}
        {typeof compaction?.last_tokens_before === "number" && typeof compaction.last_tokens_after === "number"
          ? <><dt>{t("sessionControls.lastCompaction")}</dt>
            <dd>{formattedTokens(compaction.last_tokens_before)} → {formattedTokens(compaction.last_tokens_after)}</dd></> : null}
      </dl>
      <button className="secondary-button" type="button" disabled={!canApply}
        onClick={() => void mutate({ action: "compact" })}>{t("sessionControls.compact")}</button>
    </> : null}
    {operation ? <div className="session-controls-progress">
      <p role="status">{t(submitting ? "sessionControls.submitting" : execution
        ? "sessionControls.pending" : checking ? "sessionControls.checking" : "sessionControls.unknown",
      { operation: pendingLabel })}</p>
      {!submitting && !checking && !execution
        ? <button className="secondary-button" type="button" onClick={refresh}>{t("sessionControls.check")}</button> : null}
      {operation.action === "compact" && execution
        ? <button className="secondary-button" type="button" disabled={interrupting || execution.interruptRequested}
          onClick={() => void interrupt(execution.executionId)}>{t("sessionControls.stop")}</button> : null}
    </div> : null}
    {feedback ? <p role={feedback.kind === "failed" ? "alert" : "status"}>{t(feedback.kind === "failed"
      ? "sessionControls.failed" : feedback.kind === "interrupted" ? "sessionControls.interrupted" : "sessionControls.succeeded",
    { reason: feedback.reason ?? "operation_unavailable" })}</p> : null}
    {error && !operation ? <button className="secondary-button" type="button" onClick={refresh}>{t("sessionControls.refresh")}</button> : null}
  </dialog>;
}
