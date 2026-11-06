import { i18n } from "./i18n";
import { useTranslation } from "react-i18next";
import { LanguageSelect } from "./i18n/LanguageSelect";
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import "./App.css";
import { UiIcon } from "./UiIcon";
import { DesktopFrame, PanelIcon } from "./DesktopFrame";
import { createMockAppClient } from "./client/mockAppClient";
import { createNativeLiveClient, nativeLiveAvailable } from "./client/nativeLiveClient";
import { probeFixtureBridge, type BridgeProbe } from "./client/nativeFixtureBridge";
import type {
  AgentRunProjection,
  ChangeSetProjection,
  ClientEvent,
  FixturePlaybackPort,
  HarnessClientUiPort,
  ReadonlyDocument,
  RunProjection,
  SessionSnapshot,
  SessionModels,
  TaskProjection,
  WorkspaceSummary,
} from "./client/model";
import { emptyGuiState, guiReducer, hasCapability, type DockTab, type GuiState } from "./client/state";

type NoticeKey = `notice.${keyof typeof import("./i18n/locales/en-US/session.json")["notice"]}`;
type Notice =
  | { key: Exclude<NoticeKey, "notice.rejected" | "notice.interruptReason" | "notice.playback" | "notice.modelChanged"> }
  | { key: "notice.rejected" | "notice.interruptReason"; params: { reason: string } }
  | { key: "notice.playback"; params: { label: string } }
  | { key: "notice.modelChanged"; params: { model: string } };

function NoticeText({ notice }: { notice: Notice }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  switch (notice.key) {
    case "notice.rejected":
    case "notice.interruptReason": return <>{t(notice.key)}{notice.params.reason ? <span> {t("session:diagnostic.details")}: <code>{notice.params.reason}</code></span> : null}</>;
    case "notice.playback": return t(notice.key, notice.params);
    case "notice.modelChanged": return t(notice.key, notice.params);
    default: return t(notice.key);
  }
}

interface HarnessGuiProps {
  readonly client: HarnessClientUiPort | FixturePlaybackPort;
}

function fixturePlayback(client: HarnessClientUiPort): FixturePlaybackPort | null {
  return "advanceFixture" in client && "remainingFixtureSteps" in client
    ? client as FixturePlaybackPort
    : null;
}

const dockTabs = [
  { id: "environment", label: "workspace:environment.title", glyph: "◎" },
  { id: "tasks", label: "panels:dock.tasks", glyph: "☷" },
  { id: "agents", label: "panels:dock.agents", glyph: "✣" },
  { id: "review", label: "panels:changes.review", glyph: "▣" },
] as const;

export function HarnessGui({ client }: HarnessGuiProps) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const fixture = fixturePlayback(client);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [environmentOpen, setEnvironmentOpen] = useState(true);
  const [viewportWidth, setViewportWidth] = useState(window.innerWidth);
  const [contentMetrics, setContentMetrics] = useState({ gutter: 24, scrollbar: 0 });
  const conversationRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const resize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const sidebarDrag = useRef<{ x: number; width: number } | null>(null);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.ctrlKey && !event.altKey && !event.shiftKey && !event.isComposing && !event.repeat && event.key.toLowerCase() === "b") {
        event.preventDefault(); setSidebarOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  const [state, dispatch] = useReducer(guiReducer, undefined, emptyGuiState);
  const [notice, setNotice] = useState<Notice>({ key: "notice.loading" });
  const [syncing, setSyncing] = useState(true);
  const refreshRef = useRef<(() => void) | null>(null);
  const syncPendingRef = useRef(true);
  const [remainingSteps, setRemainingSteps] = useState(fixture?.remainingFixtureSteps() ?? 0);
  const [controlPending, setControlPending] = useState<"submit" | "interrupt" | null>(null);
  const [sessionModels, setSessionModels] = useState<SessionModels | null>(null);
  const [modelPending, setModelPending] = useState(false);
  const [createPending, setCreatePending] = useState(false);
  const createdSessionRef = useRef<string | null>(null);
  const controlPendingRef = useRef(false);
  const [awaitingPublication, setAwaitingPublication] = useState<{
    readonly sessionId: string;
    readonly cursor: string;
  } | null>(null);
  const [bridgeProbe, setBridgeProbe] = useState<BridgeProbe>({
    status: "web-mock",
    label: "Web Mock",
  });
  const submissionCounter = useRef(1);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const quickLookTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreQuickLookFocusRef = useRef(false);

  useEffect(() => {
    let active = true;
    let pending = false;
    let buffered: ClientEvent[] = [];
    let overflow = false;
    async function refresh(): Promise<void> {
      if (!active || pending) return;
      pending = true;
      syncPendingRef.current = true;
      buffered = [];
      overflow = false;
      setSyncing(true);
      try {
        const snapshot = await client.snapshot();
        if (!active) return;
        if (overflow) throw new Error("Snapshot event buffer exceeded its limit.");
        dispatch({ type: "snapshot.installed", snapshot });
        // The reducer ignores cursors already covered by the snapshot and freezes
        // on any remaining gap. Never infer continuity from arrival timing.
        for (const event of buffered) dispatch({ type: "event.received", event });
        setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
        setNotice(snapshot.source.kind === "fixture"
          ? { key: "notice.fixtureReady" }
          : { key: "notice.liveReady" });
      } catch {
        if (active) dispatch({
          type: "sync.failed",
          message: fixture
            ? "Fixture synchronization failed. Retry to load a fresh snapshot."
            : "Live snapshot synchronization failed. Restart the native connection.",
        });
      } finally {
        if (active) {
          buffered = [];
          pending = false;
          syncPendingRef.current = false;
          setSyncing(false);
        }
      }
    }
    refreshRef.current = () => { void refresh(); };
    const unsubscribe = client.subscribe((event) => {
      if (!active) return;
      if (pending) {
        if (buffered.length < 2048) buffered.push(event);
        else overflow = true;
      } else dispatch({ type: "event.received", event });
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
    });
    const unsubscribeSnapshots = client.subscribeSnapshots?.((snapshot) => {
      if (!active) return;
      dispatch({ type: "snapshot.installed", snapshot });
      const createdSessionId = createdSessionRef.current;
      if (createdSessionId && snapshot.sessions.some((session) => session.id === createdSessionId)) {
        createdSessionRef.current = null;
        dispatch({ type: "session.selected", sessionId: createdSessionId });
        setCreatePending(false);
        setNotice({ key: "notice.created" });
      } else {
        setNotice({ key: "notice.liveUpdated" });
      }
      setSyncing(false);
    }) ?? (() => undefined);
    const unsubscribeConnection = client.subscribeConnection?.((connection) => {
      if (!active) return;
      dispatch({
        type: "connection.changed",
        connection,
        message: connection === "disconnected"
          ? "Live AppHost disconnected. Reconnecting from a fresh snapshot."
          : "Live event continuity was lost. Requesting a fresh snapshot.",
      });
      setSyncing(true);
    }) ?? (() => undefined);
    void refresh();
    if (fixture) void probeFixtureBridge().then((probe) => {
      if (active) setBridgeProbe(probe);
    });
    return () => {
      active = false;
      refreshRef.current = null;
      unsubscribe();
      unsubscribeSnapshots();
      unsubscribeConnection();
    };
  }, [client, fixture]);

  const resyncRequestedRef = useRef(false);
  useEffect(() => {
    if (state.remote.connection !== "resync-required") {
      resyncRequestedRef.current = false;
      return;
    }
    if (!client.requestResync || resyncRequestedRef.current) return;
    resyncRequestedRef.current = true;
    void client.requestResync().catch(() => {
      dispatch({
        type: "connection.changed",
        connection: "disconnected",
        message: "Unable to request live resynchronization.",
      });
    });
  }, [client, state.remote.connection]);

  useEffect(() => {
    if (!state.local.quickLookDocumentId && restoreQuickLookFocusRef.current) {
      restoreQuickLookFocusRef.current = false;
      quickLookTriggerRef.current?.focus();
    }
  }, [state.local.quickLookDocumentId]);

  const selectedId = state.local.selectedSessionId;
  const panelOpen = state.local.dockOpen && state.local.dockTab !== "environment";
  useEffect(() => { if (panelOpen) setEnvironmentOpen(false); }, [panelOpen]);
  const rightVisible = environmentOpen || panelOpen;
  const rightWidth = environmentOpen ? 330 : 380;
  const remainingWidth = viewportWidth - (sidebarOpen && viewportWidth > 760 ? sidebarWidth : 0);
  const stackedRight = rightVisible && remainingWidth < rightWidth + 360;
  const tasksAvailable = hasCapability(state, "tasks");
  const changesAvailable = hasCapability(state, "changes");
  const selected = selectedId ? state.remote.sessions[selectedId] : undefined;
  useEffect(() => {
    let active = true;
    setSessionModels(null);
    if (!selectedId || state.remote.connection !== "connected" || !client.sessionModels) return () => { active = false; };
    void client.sessionModels(selectedId).then((models) => {
      if (active) setSessionModels(models);
    }).catch(() => {
      if (active) setNotice({ key: "notice.modelsUnavailable" });
    });
    return () => { active = false; };
  }, [client, selectedId, state.remote.connection]);
  useEffect(() => {
    if (!awaitingPublication) return;
    const session = state.remote.sessions[awaitingPublication.sessionId];
    if (state.remote.connection !== "connected" || !session || session.cursor !== awaitingPublication.cursor) {
      setAwaitingPublication(null);
    }
  }, [awaitingPublication, state.remote.connection, state.remote.sessions]);
  const mutationsAllowed = !syncing && !controlPending && !awaitingPublication && (
    (state.remote.source.kind === "fixture" && state.remote.connection === "fixture-offline")
    || (state.remote.source.kind === "live" && state.remote.connection === "connected")
  );
  useLayoutEffect(() => {
    const pane = conversationRef.current;
    const transcript = transcriptRef.current;
    if (!pane || !transcript || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const scrollbar = Math.max(0, transcript.offsetWidth - transcript.clientWidth);
      const gutter = Math.max(24, (pane.clientWidth - scrollbar - 760) / 2);
      setContentMetrics((old) => old.gutter === gutter && old.scrollbar === scrollbar ? old : { gutter, scrollbar });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(pane);
    observer.observe(transcript);
    return () => observer.disconnect();
  }, [selected?.id]);
  useLayoutEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = state.local.transcriptScrollTop;
  }, [selected, state.local.transcriptScrollTop]);
  const selectedDocument = selected
    ? findSelectedDocument(selected, state.local.selectedDocuments[selected.id] ?? null)
    : undefined;
  const quickLookDocument = selected?.documents.find(
    (document) => document.id === state.local.quickLookDocumentId,
  );

  async function submit(): Promise<void> {
    if (!selected || syncPendingRef.current || controlPendingRef.current || !mutationsAllowed || selected.status === "running") return;
    const text = state.local.drafts[selected.id] ?? "";
    if (!text.trim()) {
      setNotice({ key: "notice.emptyPrompt" });
      return;
    }
    const submissionId = fixture
      ? `gui-fixture-submission-${submissionCounter.current++}`
      : `gui-${crypto.randomUUID()}`;
    controlPendingRef.current = true;
    setControlPending("submit");
    try {
      const receipt = await client.submitText({ sessionId: selected.id, submissionId, text });
      if (!receipt.accepted) {
        setNotice(receipt.reason === "submission_outcome_unknown"
          ? { key: "notice.unknownSubmission" }
          : { key: "notice.rejected", params: { reason: receipt.reason ?? "" } });
        return;
      }
      dispatch({ type: "draft.submitted", sessionId: selected.id, expected: text });
      if (!fixture) setAwaitingPublication({ sessionId: selected.id, cursor: selected.cursor });
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
      setNotice(fixture
        ? { key: "notice.fixtureAccepted" }
        : { key: "notice.liveAccepted" });
    } catch {
      setNotice({ key: "notice.submitFailed" });
    } finally {
      controlPendingRef.current = false;
      setControlPending(null);
    }
  }

  async function advance(): Promise<void> {
    if (!fixture || syncPendingRef.current || !mutationsAllowed) return;
    const step = await fixture.advanceFixture();
    if (!step) {
      setNotice({ key: "notice.noEvent" });
      return;
    }
    setRemainingSteps(step.remaining);
    setNotice({ key: "notice.playback", params: { label: step.label } });
  }

  async function interrupt(): Promise<void> {
    if (!selected || syncPendingRef.current || controlPendingRef.current || !mutationsAllowed || selected.status !== "running") return;
    controlPendingRef.current = true;
    setControlPending("interrupt");
    try {
      const receipt = await client.interrupt(selected.id);
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
      setNotice(receipt.accepted
        ? (fixture ? { key: "notice.fixtureInterrupted" } : { key: "notice.interruptRequested" })
        : { key: "notice.interruptReason", params: { reason: receipt.reason ?? "" } });
    } catch {
      setNotice({ key: "notice.interruptFailed" });
    } finally {
      controlPendingRef.current = false;
      setControlPending(null);
    }
  }

  async function selectModel(modelId: string): Promise<void> {
    if (!selected || !client.selectModel || selected.status === "running" || modelPending) return;
    setModelPending(true);
    try {
      const models = await client.selectModel(selected.id, modelId);
      setSessionModels(models);
      const choice = models.models.find((model) => model.id === models.currentId);
      setNotice({ key: "notice.modelChanged", params: { model: choice?.label ?? modelId } });
    } catch {
      setNotice({ key: "notice.modelRejected" });
    } finally {
      setModelPending(false);
    }
  }

  async function createSession(): Promise<void> {
    if (!selected || !client.createSession || createPending
      || state.remote.connection !== "connected") return;
    setCreatePending(true);
    try {
      const receipt = await client.createSession({
        sourceSessionId: selected.id,
        title: i18n.t("workspace:sidebar.newSession"),
      });
      createdSessionRef.current = receipt.sessionId;
      setNotice({ key: "notice.creating" });
      // Creation replaces the mux projection and invalidates the old controller.
      // Ask for another authoritative snapshot as a race-safe fallback in case
      // the automatic reconnect completed before the command reply reached UI.
      void client.requestResync?.().catch(() => undefined);
    } catch {
      setCreatePending(false);
      setNotice({ key: "notice.createFailed" });
    }
  }

  function openReview(documentId: string): void {
    if (!selected) return;
    setEnvironmentOpen(false);
    restoreQuickLookFocusRef.current = false;
    dispatch({ type: "document.selected", sessionId: selected.id, documentId });
    dispatch({ type: "dock.opened", tab: "review" });
    dispatch({ type: "quick-look.closed" });
  }

  function closeQuickLook(): void {
    restoreQuickLookFocusRef.current = true;
    dispatch({ type: "quick-look.closed" });
  }

  return (
    <div className="desktop-shell">
      <DesktopFrame sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen((open) => !open)} />
      <main style={{ "--rail-width": `${sidebarOpen ? sidebarWidth : 0}px`, "--right-width": `${rightWidth}px` } as React.CSSProperties} className={`app-shell desktop-layout${sidebarOpen ? "" : " sidebar-closed"}${rightVisible ? " right-visible" : " dock-closed"}${stackedRight ? " right-stacked" : ""}`}>
        <div className="sidebar-container" hidden={!sidebarOpen}>
        <Sidebar
          state={state}
          bridgeProbe={bridgeProbe}
          onSelect={(sessionId) => dispatch({ type: "session.selected", sessionId })}
          onToggleWorkspace={(workspaceId) => dispatch({ type: "workspace.toggled", workspaceId })}
          onNewSession={() => { void createSession(); }}
          newSessionEnabled={Boolean(client.createSession) && state.remote.connection === "connected"}
          newSessionPending={createPending}
        />
        <div className="sidebar-resizer" role="separator" aria-label={t("panels:layout.sidebarWidth")} aria-orientation="vertical" tabIndex={0}
          aria-valuemin={200} aria-valuemax={420} aria-valuenow={sidebarWidth}
          onDoubleClick={() => setSidebarWidth(280)}
          onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setSidebarWidth((width) => Math.max(200, Math.min(420, width + (event.key === "ArrowLeft" ? -10 : 10)))); } }}
          onPointerDown={(event) => { if (event.button !== 0) return; sidebarDrag.current = { x: event.clientX, width: sidebarWidth }; event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerMove={(event) => { const drag = sidebarDrag.current; if (drag) setSidebarWidth(Math.max(200, Math.min(420, drag.width + event.clientX - drag.x))); }}
          onPointerUp={() => { sidebarDrag.current = null; }} onPointerCancel={() => { sidebarDrag.current = null; }} onLostPointerCapture={() => { sidebarDrag.current = null; }} />
        </div>

        <section ref={conversationRef} style={{ "--content-gutter": `${contentMetrics.gutter}px`, "--scrollbar-width": `${contentMetrics.scrollbar}px` } as React.CSSProperties} className="conversation-pane" aria-label={t("panels:layout.workspace")}>
          {syncing || state.diagnostic || state.remote.connection === "disconnected" ? (
            <div className="diagnostic" role="status">
              <span>{syncing ? (fixture ? t("session:sync.fixture") : t("session:sync.live")) : t("session:diagnostic.title")}</span>
              {state.diagnostic ? <details><summary>{t("session:diagnostic.details")}</summary><pre>{state.diagnostic}</pre></details> : null}
              {fixture ? <button type="button" disabled={syncing} onClick={() => refreshRef.current?.()}>{t("session:sync.retry")}</button> : null}
            </div>
          ) : null}
          {selected ? (
            <>
              <SessionHeader
                session={selected}
                connection={state.remote.connection}
                dockOpen={panelOpen}
                environmentOpen={environmentOpen}
                onEnvironment={() => { if (!environmentOpen) dispatch({ type: "dock.closed" }); setEnvironmentOpen((open) => !open); }}
                onOpenDock={() => {
                  setEnvironmentOpen(false);
                  dispatch(panelOpen ? { type: "dock.closed" } : { type: "dock.opened", tab: state.local.dockTab === "environment" ? "tasks" : state.local.dockTab });
                }}
              />
              <div className="transcript" aria-label={t("session:transcript.label")} aria-live="polite" ref={transcriptRef}
                onScroll={(event) => dispatch({ type: "transcript.scrolled", sessionId: selected.id, scrollTop: event.currentTarget.scrollTop })}>
                {selected.messages.map((message) => (
                  <article className={`message ${message.role}`} key={message.id} aria-label={t("session:transcript.message", { role: valueLabel(message.role) })}>
                    <div className="message-meta">
                      <strong>{message.role === "user" ? t("session:transcript.you") : t("session:transcript.harness")}</strong>
                      <span>{valueLabel(message.phase)}</span>
                    </div>
                    <p>{message.content || t("session:transcript.waiting")}</p>
                  </article>
                ))}
                {selected.execution ? <ExecutionDetail execution={selected.execution} /> : null}
                {selected.run && tasksAvailable ? (
                  <RunActivity
                    run={selected.run}
                    expanded={Boolean(state.local.expandedActivities[selected.run.id])}
                    onToggle={() => dispatch({ type: "activity.toggled", activityGroupId: selected.run!.id })}
                    onSelectTask={(taskId) => dispatch({ type: "task.selected", taskId })}
                  />
                ) : null}
                {selected.changeSet && changesAvailable ? (
                  <ChangeSetCard
                    changeSet={selected.changeSet}
                    onOpenFile={(documentId, trigger) => {
                      quickLookTriggerRef.current = trigger;
                      dispatch({ type: "quick-look.opened", documentId });
                    }}
                    onOpenReview={() => {
                      const first = selected.changeSet?.files[0];
                      if (first) openReview(first.documentId);
                    }}
                  />
                ) : null}
              </div>

              {quickLookDocument && changesAvailable ? (
                <QuickLook
                  document={quickLookDocument}
                  onClose={closeQuickLook}
                  onOpenReview={() => openReview(quickLookDocument.id)}
                />
              ) : null}

              {fixture ? <details className="playback-strip" aria-label={t("session:fixture.controls")}>
                <summary>{t("session:fixture.summary", { count: remainingSteps })}</summary>
                <div className="playback-body">
                <div>
                  <strong>{t("session:fixture.deterministic")}</strong>
                  <span>{t("session:fixture.queued", { count: remainingSteps })}</span>
                  <small>{t(bridgeLabels[bridgeProbe.status])}</small>
                </div>
                <button type="button" disabled={!mutationsAllowed} onClick={() => void advance()}>{t("session:fixture.advance")}</button>
                </div>
              </details> : null}

              <div className="composer-stack">
                {selected.run && tasksAvailable ? (
                  <TaskProgressControl
                    run={selected.run}
                    open={state.local.taskListOpen}
                    onToggle={() => dispatch({ type: "task-list.toggled" })}
                    onSelect={(taskId) => dispatch({ type: "task.selected", taskId })}
                  />
                ) : null}
                <form
                  className="composer"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submit();
                  }}
                >
                  <label className="visually-hidden" htmlFor="message-input">{t("session:composer.messageFor", { title: selected.title })}</label>
                  <textarea
                    id="message-input"
                    rows={2}
                    value={state.local.drafts[selected.id] ?? ""}
                    placeholder={state.remote.source.kind === "fixture" ? t("session:composer.fixturePlaceholder") : t("session:composer.livePlaceholder")}
                    onChange={(event) =>
                      dispatch({ type: "draft.changed", sessionId: selected.id, value: event.currentTarget.value })
                    }
                    onKeyDown={(event) => {
                      if (!event.nativeEvent.isComposing && event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                        event.preventDefault();
                        void submit();
                      }
                    }}
                  />
                  <div className="composer-actions">
                    <button type="button" className="icon-button" aria-label={t("session:composer.attachUnavailable")} title={t("session:composer.attachHint")} disabled>＋</button>
                    <span className="permission-label">◉ {state.remote.source.kind === "fixture" ? t("session:composer.fixtureAccess") : t("session:composer.liveControl")}</span>
                    <p className="visually-hidden" role="status"><NoticeText notice={notice} /></p>
                    <select
                      className="effort-selector"
                      aria-label={t("session:models.label")}
                      title={sessionModels ? t("session:models.changeHint") : t("session:models.unavailable")}
                      value={sessionModels?.currentId ?? ""}
                      disabled={!sessionModels?.models.length || modelPending || selected.status === "running"}
                      onChange={(event) => void selectModel(event.currentTarget.value)}
                    >
                      {!sessionModels?.currentId ? <option value="">{t("session:models.none")}</option> : null}
                      {sessionModels?.models.map((model) => (
                        <option key={model.id} value={model.id} title={t("session:models.endpoint", { endpoint: model.endpointId })}>
                          {t(model.supportsThinking ? "session:models.reasoningOption" : "session:models.option", { provider: model.provider, model: model.modelId })}
                        </option>
                      ))}
                    </select>
                    <button
                      className="composer-submit"
                      type={selected.status === "running" ? "button" : "submit"}
                      aria-label={selected.status === "running" ? t("session:composer.interrupt") : t("session:composer.send")}
                      title={selected.status === "running" ? t("session:composer.stopHint") : t("session:composer.sendHint")}
                      disabled={!mutationsAllowed || (selected.status !== "running" && !(state.local.drafts[selected.id] ?? "").trim())}
                      onClick={selected.status === "running" ? () => void interrupt() : undefined}
                    >
                      {selected.status === "running" ? <svg aria-hidden="true" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" /></svg>
                        : <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 18V6m-5 5 5-5 5 5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                    </button>
                  </div>
                </form>
              </div>
            </>
          ) : (
            <div className="empty-state">{t("session:emptySession")}</div>
          )}
        </section>

        {environmentOpen && selected ? <aside className="environment-popover" aria-label={t("workspace:environment.summary")}>
          <header><span>{t("workspace:environment.title")}</span><button type="button" className="icon-close" aria-label={t("workspace:environment.close")} onClick={() => setEnvironmentOpen(false)}><UiIcon name="close" /></button></header>
          {hasCapability(state, "workspace") ? <EnvironmentPanel state={state} session={selected} />
            : state.remote.source.kind === "live" ? <LiveContextPanel state={state} session={selected} />
              : <UnavailablePanel label={t("workspace:capability.workspace")} />}
          <div className="environment-links">
            <button type="button" disabled={!changesAvailable || !selected.changeSet?.files.length} onClick={() => { const id = selected.changeSet?.files[0]?.documentId; if (id) openReview(id); }}>{t("workspace:environment.changesLink")}</button>
            <button type="button" disabled={!hasCapability(state, "agents")} onClick={() => { setEnvironmentOpen(false); dispatch({ type: "dock.opened", tab: "agents" }); }}>{t("workspace:environment.agentsLink")}</button>
          </div>
        </aside> : null}
        {!environmentOpen && panelOpen && selected ? (
          <WorkDock
            state={state}
            session={selected}
            selectedDocument={selectedDocument}
            onClose={() => dispatch({ type: "dock.closed" })}
            onTab={(tab) => dispatch({ type: "dock.opened", tab })}
            onSelectDocument={(documentId) => dispatch({ type: "document.selected", sessionId: selected.id, documentId })}
            onSelectTask={(taskId) => dispatch({ type: "task.selected", taskId })}
            onSelectAgent={(agentRunId) => dispatch({ type: "agent.selected", agentRunId })}
          />
        ) : null}
      </main>
    </div>
  );
}

interface SidebarProps {
  readonly state: GuiState;
  readonly bridgeProbe: BridgeProbe;
  readonly onSelect: (sessionId: string) => void;
  readonly onToggleWorkspace: (workspaceId: string) => void;
  readonly onNewSession: () => void;
  readonly newSessionEnabled: boolean;
  readonly newSessionPending: boolean;
}

function Sidebar({ state, bridgeProbe, onSelect, onToggleWorkspace, onNewSession, newSessionEnabled, newSessionPending }: SidebarProps) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <aside className="session-rail" aria-label={t("workspace:sidebar.navigation")}>
      <div className="brand-row">
        {/* i18next-instrument-ignore-next-line: product name */}
        <span className="brand-name"><strong>loushang</strong><UiIcon name="chevron-down" /></span>
        <button className="brand-search" type="button" aria-label={t("workspace:sidebar.searchUnavailable")} title={t("workspace:sidebar.searchHint")} disabled><UiIcon name="search" /></button>
      </div>
      <button className="new-session" type="button" onClick={onNewSession}
        disabled={!newSessionEnabled || newSessionPending}>
        <UiIcon name="new-session" /> {newSessionPending ? t("workspace:sidebar.creating") : t("workspace:sidebar.newSession")} <kbd aria-hidden="true">+</kbd>
      </button>
      <nav className="sidebar-shortcuts" aria-label={t("workspace:sidebar.shortcuts")}>
        <button type="button" disabled title={t("workspace:sidebar.prHint")}><UiIcon name="pull-request" /><span>{t("workspace:sidebar.pullRequests")}</span></button>
        <button type="button" disabled title={t("workspace:sidebar.scheduleHint")}><UiIcon name="scheduled" /><span>{t("workspace:sidebar.scheduled")}</span></button>
        <button type="button" disabled title={t("workspace:sidebar.pluginsHint")}><UiIcon name="plugins" /><span>{t("workspace:sidebar.plugins")}</span></button>
      </nav>
      <div className="fixture-banner"><span className="fixture-dot" />{state.remote.source.kind === "fixture" ? t("workspace:sidebar.fixtureBanner") : t("workspace:sidebar.liveBanner")}</div>

      <nav className="workspace-scroll" aria-label={t("workspace:sidebar.workspaces")}>
        {!hasCapability(state, "workspace") ? state.remote.source.kind === "live" ? (
          <section className="workspace-group" aria-label={t("workspace:sidebar.attached")}>
            <div className="workspace-heading static">
              <span className="folder-glyph"><UiIcon name="folder" /></span>
              <span>{state.remote.source.muxName ?? t("workspace:sidebar.mux")}</span>
            </div>
            <div className="session-list">
              {state.remote.sessionOrder.map((id) => <SessionButton key={id} session={state.remote.sessions[id]}
                stale={isStale(state)} selected={id === state.local.selectedSessionId} unread={Boolean(state.local.unread[id])} onSelect={() => onSelect(id)} />)}
            </div>
            <p className="section-label">{t("workspace:sidebar.workspaceUnavailable")}</p>
          </section>
        ) : <>
          <UnavailablePanel label={t("workspace:capability.workspace")} />
          {state.remote.sessionOrder.map((id) => <SessionButton key={id} session={state.remote.sessions[id]}
            stale={isStale(state)} selected={id === state.local.selectedSessionId} unread={Boolean(state.local.unread[id])} onSelect={() => onSelect(id)} />)}
        </> : state.remote.workspaceOrder.map((workspaceId) => {
          const workspace = state.remote.workspaces[workspaceId];
          const sessions = state.remote.sessionOrder
            .map((id) => state.remote.sessions[id])
            .filter((session) => session.workspaceId === workspaceId);
          const expanded = state.local.expandedWorkspaces[workspaceId] ?? true;
          return (
            <section className="workspace-group" key={workspace.id}>
              <button
                className="workspace-heading"
                type="button"
                aria-expanded={expanded}
                onClick={() => onToggleWorkspace(workspace.id)}
              >
                <span className="folder-glyph"><UiIcon name="folder" /></span>
                <span>{workspace.title}</span>
                <VcsBadge workspace={workspace} />
                <UiIcon name={expanded ? "chevron-up" : "chevron-down"} />
              </button>
              {expanded ? (
                <div className="session-list">
                  {sessions.map((session) => (
                    <SessionButton
                      key={session.id}
                      session={session}
                      stale={isStale(state)}
                      selected={session.id === state.local.selectedSessionId}
                      unread={Boolean(state.local.unread[session.id])}
                      onSelect={() => onSelect(session.id)}
                    />
                  ))}
                </div>
              ) : null}
            </section>
          );
        })}

        <section className="recent-group">
          <p className="section-label">{t("workspace:sidebar.recent")}</p>
          {state.remote.recentSessionIds.map((sessionId) => {
            const session = state.remote.sessions[sessionId];
            return session ? (
              <button className="recent-session" type="button" key={sessionId} onClick={() => onSelect(sessionId)}>
                <span>{session.title}</span><StatusMark status={session.status} stale={isStale(state)} />
              </button>
            ) : null;
          })}
        </section>
      </nav>

      <LanguageSelect />
      <div className="rail-footer">
        <div className="user-avatar" aria-hidden="true">Z</div>
        {/* i18next-instrument-ignore-next-line: fixture account name */}
        <div><strong>zhnt</strong><span title={state.remote.source.kind === "fixture" ? t(bridgeLabels[bridgeProbe.status]) : state.remote.source.serviceInstanceId}>{state.remote.source.kind === "fixture" ? t("workspace:sidebar.offline") : t("workspace:sidebar.live")}</span></div>
        <span aria-hidden="true">⋯</span>
      </div>
    </aside>
  );
}

function VcsBadge({ workspace }: { readonly workspace: WorkspaceSummary }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!workspace.vcs) return <span className="vcs-badge none">{t("workspace:sidebar.plain")}</span>;
  return <span className={`vcs-badge ${workspace.vcs.kind}`}>{workspace.vcs.kind} · {workspace.vcs.label}</span>;
}

function SessionButton({ session, selected, unread, stale, onSelect }: {
  readonly session: SessionSnapshot;
  readonly selected: boolean;
  readonly unread: boolean;
  readonly stale: boolean;
  readonly onSelect: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const label = stale ? t("workspace:sidebar.stale", { status: valueLabel(session.status) }) : valueLabel(session.status);
  return (
    <button
      className={`session-item${selected ? " selected" : ""}`}
      type="button"
      aria-current={selected ? "page" : undefined}
      aria-label={t("workspace:sidebar.sessionLabel", { title: session.title, status: label })}
      onClick={onSelect}
    >
      <span className="session-title">{session.title}</span>
      <StatusMark status={session.status} stale={stale} />
      {unread ? <span className="unread-dot" aria-label={t("workspace:sidebar.unread")} /> : null}
    </button>
  );
}

function StatusMark({ status, stale = false }: {
  readonly status: SessionSnapshot["status"];
  readonly stale?: boolean;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const label = stale ? t("workspace:sidebar.stale", { status: valueLabel(status) }) : valueLabel(status);
  return (
    <span className={`status-mark ${status}${stale ? " stale" : ""}`} title={label}>
      <span className="status-glyph" aria-hidden="true">{stale ? "–" : status === "running" ? "◌" : status === "waiting" ? "!" : status === "failed" ? "×" : ""}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

function isStale(state: GuiState): boolean {
  return state.remote.connection === "disconnected" || state.remote.connection === "resync-required";
}

function ExecutionDetail({ execution }: {
  readonly execution: NonNullable<SessionSnapshot["execution"]>;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <details className="execution-detail" aria-label={t("panels:execution.details")}>
      <summary>
        <span className={`run-indicator ${execution.status}`} aria-hidden="true">◌</span>
        <strong>{t("panels:execution.status", { status: valueLabel(execution.status) })}</strong>
        <span>{t("panels:execution.revision", { revision: execution.revision })}</span>
      </summary>
      <dl>
        <dt>{t("panels:execution.title")}</dt><dd><code>{execution.id}</code></dd>
        <dt>{t("panels:execution.source")}</dt><dd>{(execution.sourceStatus ? valueLabel(execution.sourceStatus) : null) ?? t("panels:execution.notObserved")}</dd>
        <dt>{t("panels:execution.finalCursor")}</dt><dd>{execution.finalCursor ?? t("panels:execution.notTerminal")}</dd>
        <dt>{t("session:composer.interrupt")}</dt><dd>{execution.interruptRequested ? t("panels:execution.requested") : t("panels:execution.notRequested")}</dd>
        <dt>{t("panels:execution.transcript")}</dt><dd>{execution.truncated ? t("panels:execution.truncated") : t("panels:execution.completeSnapshot")}</dd>
      </dl>
    </details>
  );
}

function SessionHeader({ session, connection, dockOpen, onOpenDock, environmentOpen, onEnvironment }: {
  readonly environmentOpen: boolean;
  readonly onEnvironment: () => void;
  readonly session: SessionSnapshot;
  readonly connection: string;
  readonly dockOpen: boolean;
  readonly onOpenDock: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const currentWorkspace = session.context.project;
  return (
    <header className="conversation-header">
      <div className="session-heading">
        <UiIcon name="folder" />
        <div><h1>{session.title}</h1><p>{currentWorkspace} · {session.context.muxId}</p></div>
        <button type="button" aria-label={t("panels:header.actions")}><span aria-hidden="true">⋯</span></button>
      </div>
      <div className="header-actions">
        <span className={`connection-chip ${connection}`} title={connectionLabel(connection)}>{connectionLabel(connection)}</span>
        <button type="button" aria-label={t("panels:header.shareUnavailable")} disabled>{t("panels:header.share")}</button>
        <button type="button" aria-label={t("panels:header.toggleEnvironment")} title={t("workspace:environment.title")} aria-pressed={environmentOpen} onClick={onEnvironment}><PanelIcon side="environment" /></button>
        <button type="button" aria-label={t("panels:header.bottomUnavailable")} title={t("panels:header.bottomHint")} disabled><PanelIcon side="bottom" /></button>
        <button type="button" aria-label={t("panels:header.openDock")} title={t("panels:header.toggleDock")} aria-pressed={dockOpen} onClick={onOpenDock}><PanelIcon side="right" /></button>
      </div>
    </header>
  );
}

function RunActivity({ run, expanded, onToggle, onSelectTask }: {
  readonly run: RunProjection;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const failures = run.activities.filter((activity) => activity.status === "failed").length;
  return (
    <section className="run-activity" aria-label={t("panels:activity.label")}>
      <button className="activity-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <span className={`run-indicator ${run.status}`} aria-hidden="true">◌</span>
        <span><strong>{run.title}</strong><small>{t("panels:activity.summary", { activities: run.activities.length, failures })}</small></span>
        <span aria-hidden="true">{expanded ? "⌃" : "⌄"}</span>
      </button>
      {expanded ? (
        <ol className="activity-list">
          {run.activities.map((activity) => (
            <li key={activity.id}>
              <span className={`activity-kind ${activity.kind}`} aria-hidden="true">{activityGlyph(activity.kind)}</span>
              <div>
                <button type="button" onClick={() => onSelectTask(activity.taskId)}>{activity.label}</button>
                {activity.detail ? <code>{activity.detail}</code> : null}
              </div>
              <span>{activity.durationLabel ?? valueLabel(activity.status)}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function TaskProgressControl({ run, open, onToggle, onSelect }: {
  readonly run: RunProjection;
  readonly open: boolean;
  readonly onToggle: () => void;
  readonly onSelect: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const currentIndex = run.currentTaskId ? run.tasks.findIndex((task) => task.id === run.currentTaskId) : -1;
  const completed = run.tasks.filter((task) => task.status === "completed").length;
  const label = currentIndex >= 0 ? t("panels:progress.step", { current: currentIndex + 1, total: run.tasks.length }) : t("panels:progress.complete", { completed, total: run.tasks.length });
  return (
    <div className="task-progress-wrap">
      {open ? (
        <div className="task-popover" aria-label={t("panels:progress.tasks")}>
          {run.tasks.map((task) => (
            <button type="button" key={task.id} className={task.id === run.currentTaskId ? "current" : ""} onClick={() => onSelect(task.id)}>
              <TaskStatusGlyph status={task.status} /><span>{task.title}</span>
            </button>
          ))}
        </div>
      ) : null}
      <button className="task-progress" type="button" aria-expanded={open} onClick={onToggle}>
        <span className={`task-dot ${run.status}`} aria-hidden="true" />{label}
      </button>
    </div>
  );
}

function ChangeSetCard({ changeSet, onOpenFile, onOpenReview }: {
  readonly changeSet: ChangeSetProjection;
  readonly onOpenFile: (documentId: string, trigger: HTMLButtonElement) => void;
  readonly onOpenReview: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <section className="change-card" aria-label={t("panels:changes.label")}>
      <header>
        <span className="change-icon" aria-hidden="true">▣</span>
        <div><strong>{t("panels:changes.edited", { count: changeSet.files.length })}</strong><small>{changeSet.scopeLabel}</small></div>
        <span className="additions">{t("common:additions", { value: changeSet.additions })}</span><span className="deletions">{t("common:deletions", { value: changeSet.deletions })}</span>
        <button type="button" onClick={onOpenReview}>{t("panels:changes.review")}</button>
      </header>
      <div className="change-files">
        {changeSet.files.map((file) => (
          <button type="button" key={file.id} onClick={(event) => onOpenFile(file.documentId, event.currentTarget)}>
            <span>{file.path}</span><span className="additions">{t("common:additions", { value: file.additions })}</span><span className="deletions">{t("common:deletions", { value: file.deletions })}</span>
          </button>
        ))}
      </div>
      <footer><code>{changeSet.revision}</code><span>{t("panels:changes.readOnly")}</span></footer>
    </section>
  );
}

function QuickLook({ document, onClose, onOpenReview }: {
  readonly document: ReadonlyDocument;
  readonly onClose: () => void;
  readonly onOpenReview: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <aside className="quick-look" aria-label={t("panels:review.quickLook", { title: document.title })}>
      <header><strong>{document.title}</strong><button type="button" className="icon-close" onClick={onClose} aria-label={t("panels:review.closeQuickLook")}><UiIcon name="close" /></button></header>
      <DocumentView document={document} compact />
      <footer><button type="button" onClick={onOpenReview}>{t("panels:review.openFull")}</button></footer>
    </aside>
  );
}

interface WorkDockProps {
  readonly state: GuiState;
  readonly session: SessionSnapshot;
  readonly selectedDocument: ReadonlyDocument | undefined;
  readonly onClose: () => void;
  readonly onTab: (tab: DockTab) => void;
  readonly onSelectDocument: (documentId: string) => void;
  readonly onSelectTask: (taskId: string) => void;
  readonly onSelectAgent: (agentRunId: string) => void;
}

function WorkDock(props: WorkDockProps) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const { state, session, selectedDocument, onClose, onTab, onSelectDocument, onSelectTask, onSelectAgent } = props;
  const facet = state.local.dockTab === "environment" ? "workspace" : state.local.dockTab === "review" ? "changes" : state.local.dockTab;
  const available = hasCapability(state, facet);
  const visibleRun = session.run ? {
    ...session.run,
    tasks: hasCapability(state, "tasks") ? session.run.tasks : [],
    agentRuns: hasCapability(state, "agents") ? session.run.agentRuns : [],
  } : null;
  return (
    <aside className={`work-dock${state.local.dockTab === "environment" ? " environment-card" : ""}`} aria-label={t("panels:dock.title")}>
      <header className="dock-header">
        <strong>{t(dockTabs.find((tab) => tab.id === state.local.dockTab)!.label)}</strong>
        <button type="button" className="icon-close" onClick={onClose} aria-label={t("panels:dock.close")}><UiIcon name="close" /></button>
      </header>
      <nav className="dock-tabs" aria-label={t("panels:dock.panels")}>
        {dockTabs.filter((tab) => tab.id !== "environment").map((tab) => (
          <button type="button" key={tab.id} aria-pressed={state.local.dockTab === tab.id} onClick={() => onTab(tab.id)}>
            <span aria-hidden="true">{tab.glyph}</span><span>{t(tab.label)}</span>
          </button>
        ))}
      </nav>
      <div className="dock-content">
        {!available ? state.local.dockTab === "environment" && state.remote.source.kind === "live"
          ? <LiveContextPanel state={state} session={session} />
          : <UnavailablePanel label={t("workspace:capability.missing", { capability: capabilityLabel(facet) })} /> : <>
        {state.local.dockTab === "environment" ? <EnvironmentPanel state={state} session={session} /> : null}
        {state.local.dockTab === "tasks" ? (
          <TasksPanel run={visibleRun} selectedTaskId={state.local.selectedTaskId} onSelectTask={onSelectTask} onSelectAgent={onSelectAgent} />
        ) : null}
        {state.local.dockTab === "agents" ? (
          <AgentsPanel run={visibleRun} selectedAgentRunId={state.local.selectedAgentRunId} onSelectAgent={onSelectAgent} onSelectTask={onSelectTask} />
        ) : null}
        {state.local.dockTab === "review" ? (
          <ReviewPanel session={session} selectedDocument={selectedDocument} onSelectDocument={onSelectDocument} />
        ) : null}
        </>}
      </div>
    </aside>
  );
}

function EnvironmentPanel({ state, session }: { readonly state: GuiState; readonly session: SessionSnapshot }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const workspace = state.remote.workspaces[session.workspaceId];
  return (
    <section className="panel-stack" aria-label={t("workspace:environment.details")}>
      <p className="fixture-panel-label">{t("workspace:environment.fixture")}</p>
      <dl className="detail-list">
        <div><dt>{t("workspace:environment.workspace")}</dt><dd>{workspace?.title ?? t("workspace:environment.unavailable")}</dd></div>
        <div><dt>{t("workspace:environment.root")}</dt><dd>{workspace?.rootLabel ?? session.context.rootLabel}</dd></div>
        <div><dt>{t("workspace:environment.vcs")}</dt><dd>{workspace?.vcs ? `${workspace.vcs.kind} · ${workspace.vcs.label}` : t("workspace:environment.none")}</dd></div>
        <div><dt>{t("workspace:environment.application")}</dt><dd>{session.context.applicationId}</dd></div>
        <div><dt>{t("workspace:environment.member")}</dt><dd>{session.context.muxId} / {session.context.memberId}</dd></div>
        <div><dt>{t("workspace:environment.session")}</dt><dd>{session.context.sessionId}</dd></div>
        <div><dt>{t("workspace:environment.generation")}</dt><dd>{state.remote.generation}</dd></div>
      </dl>
      <h2>{t("workspace:environment.capabilities")}</h2>
      <div className="capability-list">
        {state.remote.capabilities.map((capability) => (
          <span className={`capability ${capability.availability}`} key={capability.name}>
            {capabilityLabel(capability.name)} · {capability.version ?? t("workspace:environment.unavailableValue")}
          </span>
        ))}
      </div>
    </section>
  );
}

function LiveContextPanel({ state, session }: { readonly state: GuiState; readonly session: SessionSnapshot }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const source = state.remote.source;
  if (source.kind !== "live") return null;
  return (
    <section className="panel-stack" aria-label={t("workspace:live.context")}>
      <p className="fixture-panel-label">{t("workspace:live.identity")}</p>
      <dl className="detail-list">
        <div><dt>{t("workspace:live.product")}</dt><dd>{session.context.project}</dd></div>
        <div><dt>{t("workspace:live.scope")}</dt><dd>{session.context.scope ?? t("workspace:environment.unavailable")}</dd></div>
        <div><dt>{t("workspace:live.fingerprint")}</dt><dd>{session.context.scopeFingerprint ?? t("workspace:environment.unavailable")}</dd></div>
        <div><dt>{t("workspace:live.mux")}</dt><dd>{source.muxName ?? source.muxSpaceId}</dd></div>
        <div><dt>{t("workspace:environment.session")}</dt><dd>{session.context.sessionId}</dd></div>
        <div><dt>{t("workspace:live.service")}</dt><dd>{source.serviceInstanceId}</dd></div>
      </dl>
      <UnavailablePanel label={t("workspace:capability.workspace")} />
    </section>
  );
}

function TasksPanel({ run, selectedTaskId, onSelectTask, onSelectAgent }: {
  readonly run: RunProjection | null;
  readonly selectedTaskId: string | null;
  readonly onSelectTask: (taskId: string) => void;
  readonly onSelectAgent: (agentRunId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!run) return <UnavailablePanel label={t("panels:tasks.projection")} />;
  const selected = run.tasks.find((task) => task.id === selectedTaskId) ?? run.tasks[0];
  return (
    <section className="panel-stack" aria-label={t("panels:tasks.details")}>
      <p className="fixture-panel-label">{t("panels:tasks.summary", { status: valueLabel(run.status), count: run.tasks.length })}</p>
      <div className="task-tree">
        {run.tasks.map((task) => (
          <button type="button" key={task.id} className={task.id === selected?.id ? "selected" : ""} onClick={() => onSelectTask(task.id)}>
            <TaskStatusGlyph status={task.status} /><span>{task.title}</span>
          </button>
        ))}
      </div>
      {selected ? <TaskDetail task={selected} run={run} onSelectAgent={onSelectAgent} /> : null}
    </section>
  );
}

function TaskDetail({ task, run, onSelectAgent }: {
  readonly task: TaskProjection;
  readonly run: RunProjection;
  readonly onSelectAgent: (agentRunId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const activities = run.activities.filter((activity) => task.activityIds.includes(activity.id));
  return (
    <article className="selection-detail">
      <span className={`detail-status ${task.status}`}>{valueLabel(task.status)}</span>
      <h2>{task.title}</h2>
      <p>{t("panels:tasks.activities", { count: activities.length })}</p>
      <h3>{t("panels:tasks.assignedAgents")}</h3>
      {task.assignedAgentRunIds.map((agentRunId) => {
        const agent = run.agentRuns.find((item) => item.id === agentRunId);
        return agent ? <button type="button" key={agent.id} onClick={() => onSelectAgent(agent.id)}>{t("common:openItem", { title: agent.label })}</button> : null;
      })}
    </article>
  );
}

function AgentsPanel({ run, selectedAgentRunId, onSelectAgent, onSelectTask }: {
  readonly run: RunProjection | null;
  readonly selectedAgentRunId: string | null;
  readonly onSelectAgent: (agentRunId: string) => void;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!run) return <UnavailablePanel label={t("panels:agents.projection")} />;
  const selected = run.agentRuns.find((agent) => agent.id === selectedAgentRunId) ?? run.agentRuns[0];
  return (
    <section className="panel-stack" aria-label={t("panels:agents.details")}>
      <p className="fixture-panel-label">{t("panels:agents.summary", { count: run.agentRuns.length })}</p>
      <div className="agent-tree">
        {run.agentRuns.map((agent) => (
          <button type="button" key={agent.id} className={agent.id === selected?.id ? "selected" : ""} onClick={() => onSelectAgent(agent.id)}>
            <span className={`agent-avatar ${agent.role}`} aria-hidden="true">{agent.role === "root" ? "H" : "R"}</span>
            <span><strong>{agent.label}</strong><small>{valueLabel(agent.role)} · {valueLabel(agent.status)}</small></span>
          </button>
        ))}
      </div>
      {selected ? <AgentDetail agent={selected} run={run} onSelectTask={onSelectTask} /> : null}
    </section>
  );
}

function AgentDetail({ agent, run, onSelectTask }: {
  readonly agent: AgentRunProjection;
  readonly run: RunProjection;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <article className="selection-detail">
      <span className={`detail-status ${agent.status}`}>{valueLabel(agent.status)}</span>
      <h2>{agent.label}</h2><p>{agent.summary ?? t("panels:agents.noSummary")}</p>
      <h3>{t("panels:agents.assignedTasks")}</h3>
      {agent.taskIds.map((taskId) => {
        const task = run.tasks.find((item) => item.id === taskId);
        return task ? <button type="button" key={task.id} onClick={() => onSelectTask(task.id)}>{t("common:openItem", { title: task.title })}</button> : null;
      })}
    </article>
  );
}

function ReviewPanel({ session, selectedDocument, onSelectDocument }: {
  readonly session: SessionSnapshot;
  readonly selectedDocument: ReadonlyDocument | undefined;
  readonly onSelectDocument: (documentId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const changeDocuments = session.changeSet?.files
    .map((file) => session.documents.find((document) => document.id === file.documentId))
    .filter((document): document is ReadonlyDocument => Boolean(document)) ?? [];
  if (!session.changeSet) return <UnavailablePanel label={t("panels:review.projection")} />;
  const visibleDocument = selectedDocument?.kind === "diff" ? selectedDocument : changeDocuments[0];
  return (
    <section className="review-panel" aria-label={t("panels:review.label")}>
      <header>
        <div><strong>{session.changeSet.scopeLabel}</strong><span><b>{t("common:additions", { value: session.changeSet.additions })}</b> <em>{t("common:deletions", { value: session.changeSet.deletions })}</em></span></div>
        <button type="button" disabled>{t("panels:review.commit")}</button>
      </header>
      <div className="review-files">
        {changeDocuments.map((document) => (
          <button type="button" key={document.id} className={document.id === visibleDocument?.id ? "selected" : ""} onClick={() => onSelectDocument(document.id)}>{document.title}</button>
        ))}
      </div>
      {visibleDocument ? <DocumentView document={visibleDocument} /> : <p>{t("panels:review.noDiff")}</p>}
    </section>
  );
}

function UnavailablePanel({ label }: { readonly label: string }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return <div className="unavailable-panel"><strong>{t("common:unavailableTitle", { label })}</strong><p>{t("common:unavailableExplanation")}</p></div>;
}

function DocumentView({ document, compact = false }: { readonly document: ReadonlyDocument; readonly compact?: boolean }) {
  useTranslation(["session", "workspace", "panels", "common"]);
  const lines = document.content.split("\n");
  return (
    <article className={`document-view${compact ? " compact" : ""}`} aria-label={document.title}>
      <header><span>{valueLabel(document.kind)}</span><code>{document.revision}</code></header>
      <p className="document-source">{document.sourceLabel}</p>
      <pre>{lines.map((line, index) => <span className={diffLineClass(document, line)} key={`${index}-${line}`}>{line || " "}{index < lines.length - 1 ? "\n" : ""}</span>)}</pre>
    </article>
  );
}

function TaskStatusGlyph({ status }: { readonly status: TaskProjection["status"] }) {
  useTranslation(["session", "workspace", "panels", "common"]);
  const glyph = status === "completed" ? "✓" : status === "running" ? "◌" : status === "failed" ? "×" : status === "cancelled" ? "–" : "○";
  return <span className={`task-status ${status}`} aria-label={valueLabel(status)}>{glyph}</span>;
}

function diffLineClass(document: ReadonlyDocument, line: string): string {
  if (document.kind !== "diff") return "";
  if (line.startsWith("+") && !line.startsWith("+++")) return "diff-added";
  if (line.startsWith("-") && !line.startsWith("---")) return "diff-removed";
  if (line.startsWith("@@")) return "diff-hunk";
  return "";
}

function activityGlyph(kind: RunProjection["activities"][number]["kind"]): string {
  return { plan: "◴", read: "▤", command: ">_", tool: "◇", wait: "…", result: "✓" }[kind];
}

function findSelectedDocument(session: SessionSnapshot, selectedDocumentId: string | null): ReadonlyDocument | undefined {
  return session.documents.find((document) => document.id === selectedDocumentId) ?? session.documents[0];
}


const bridgeLabels = { "web-mock": "session:bridge.web-mock", locked: "session:bridge.locked", verified: "session:bridge.verified" } as const;
const valueLabels = {
  "idle": "common:status.idle",
  "running": "common:status.running",
  "waiting": "common:status.waiting",
  "interrupted": "common:status.interrupted",
  "failed": "common:status.failed",
  "completed": "common:status.completed",
  "cancelled": "common:status.cancelled",
  "pending": "common:status.pending",
  "succeeded": "common:status.succeeded",
  "streaming": "common:status.streaming",
  "root": "common:status.root",
  "subagent": "common:status.subagent",
  "assistant": "common:status.assistant",
  "user": "common:status.user",
  "diff": "common:status.diff",
  "markdown": "common:status.markdown",
  "text": "common:status.text",
  "sent": "common:status.sent",
  "complete": "common:status.complete",
  "accepted": "common:status.accepted"
} as const;
function valueLabel(value: keyof typeof valueLabels): string { return i18n.t(valueLabels[value]); }
function capabilityLabel(value: string): string {
  switch (value) {
    case "workspace": return i18n.t("workspace:environment.workspace");
    case "tasks": return i18n.t("panels:dock.tasks");
    case "agents": return i18n.t("panels:dock.agents");
    case "artifacts": return i18n.t("workspace:environment.artifacts");
    case "changes": return i18n.t("panels:changes.review");
    default: return value;
  }
}



function connectionLabel(connection: string): string {
  return { "fixture-offline": i18n.t("workspace:sidebar.offline"), connected: i18n.t("common:connection.connected"), disconnected: i18n.t("common:connection.disconnected"), "resync-required": i18n.t("common:connection.resync") }[connection] ?? connection;
}

function App() {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const fixture = useMemo(() => createMockAppClient(), []);
  const [client, setClient] = useState<HarnessClientUiPort | FixturePlaybackPort | null>(null);
  useEffect(() => {
    let active = true;
    void nativeLiveAvailable()
      .then((available) => {
        if (active) setClient(available ? createNativeLiveClient() : fixture);
      })
      .catch(() => {
        if (active) setClient(fixture);
      });
    return () => { active = false; };
  }, [fixture]);
  return client ? <HarnessGui client={client} /> : <div className="empty-state">{t("session:opening")}</div>;
}

export default App;
