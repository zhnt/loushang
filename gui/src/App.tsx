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
  TaskProjection,
  WorkspaceSummary,
} from "./client/model";
import { emptyGuiState, guiReducer, hasCapability, type DockTab, type GuiState } from "./client/state";

interface HarnessGuiProps {
  readonly client: HarnessClientUiPort | FixturePlaybackPort;
}

function fixturePlayback(client: HarnessClientUiPort): FixturePlaybackPort | null {
  return "advanceFixture" in client && "remainingFixtureSteps" in client
    ? client as FixturePlaybackPort
    : null;
}

const dockTabs: readonly { id: DockTab; label: string; glyph: string }[] = [
  { id: "environment", label: "Environment", glyph: "◎" },
  { id: "tasks", label: "Tasks", glyph: "☷" },
  { id: "agents", label: "Subagents", glyph: "✣" },
  { id: "review", label: "Review", glyph: "▣" },
];

export function HarnessGui({ client }: HarnessGuiProps) {
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
  const [notice, setNotice] = useState("Loading snapshot…");
  const [syncing, setSyncing] = useState(true);
  const refreshRef = useRef<(() => void) | null>(null);
  const syncPendingRef = useRef(true);
  const [remainingSteps, setRemainingSteps] = useState(fixture?.remainingFixtureSteps() ?? 0);
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
          ? "Fixture snapshot installed. No backend is running."
          : "Read-only live snapshot installed.");
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
      setNotice("Read-only live event round installed.");
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
  const mutationsAllowed = !syncing && state.remote.source.kind === "fixture" && state.remote.connection === "fixture-offline";
  const selected = selectedId ? state.remote.sessions[selectedId] : undefined;
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
    if (!selected || syncPendingRef.current || !mutationsAllowed || selected.status === "running") return;
    const text = state.local.drafts[selected.id] ?? "";
    if (!text.trim()) {
      setNotice("Enter a fixture prompt before sending.");
      return;
    }
    const submissionId = `gui-fixture-submission-${submissionCounter.current++}`;
    const receipt = await client.submitText({ sessionId: selected.id, submissionId, text });
    if (!receipt.accepted) {
      setNotice("The fixture rejected this submission.");
      return;
    }
    dispatch({ type: "draft.changed", sessionId: selected.id, value: "" });
    setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
    setNotice("Fixture accepted the prompt. Advance it step by step.");
  }

  async function advance(): Promise<void> {
    if (!fixture || syncPendingRef.current || !mutationsAllowed) return;
    const step = await fixture.advanceFixture();
    if (!step) {
      setNotice("No fixture event is waiting.");
      return;
    }
    setRemainingSteps(step.remaining);
    setNotice(`Playback: ${step.label}.`);
  }

  async function interrupt(): Promise<void> {
    if (!selected || syncPendingRef.current || !mutationsAllowed || selected.status !== "running") return;
    const receipt = await client.interrupt(selected.id);
    setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
    setNotice(
      receipt.accepted
        ? "Fixture execution interrupted."
        : (receipt.reason ?? "Interrupt was not accepted."),
    );
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
          onUnavailable={() => setNotice("New Session is unavailable in this read-only slice.")}
        />
        <div className="sidebar-resizer" role="separator" aria-label="Sidebar width" aria-orientation="vertical" tabIndex={0}
          aria-valuemin={200} aria-valuemax={420} aria-valuenow={sidebarWidth}
          onDoubleClick={() => setSidebarWidth(280)}
          onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setSidebarWidth((width) => Math.max(200, Math.min(420, width + (event.key === "ArrowLeft" ? -10 : 10)))); } }}
          onPointerDown={(event) => { if (event.button !== 0) return; sidebarDrag.current = { x: event.clientX, width: sidebarWidth }; event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerMove={(event) => { const drag = sidebarDrag.current; if (drag) setSidebarWidth(Math.max(200, Math.min(420, drag.width + event.clientX - drag.x))); }}
          onPointerUp={() => { sidebarDrag.current = null; }} onPointerCancel={() => { sidebarDrag.current = null; }} onLostPointerCapture={() => { sidebarDrag.current = null; }} />
        </div>

        <section ref={conversationRef} style={{ "--content-gutter": `${contentMetrics.gutter}px`, "--scrollbar-width": `${contentMetrics.scrollbar}px` } as React.CSSProperties} className="conversation-pane" aria-label="Session workspace">
          {syncing || state.diagnostic || state.remote.connection === "disconnected" ? (
            <div className="diagnostic" role="status">
              <span>{syncing ? (fixture ? "Synchronizing fixture…" : "Connecting read-only…") : state.diagnostic ?? "Disconnected."}</span>
              {fixture ? <button type="button" disabled={syncing} onClick={() => refreshRef.current?.()}>Resynchronize fixture</button> : null}
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
              <div className="transcript" aria-label="Session transcript" aria-live="polite" ref={transcriptRef}
                onScroll={(event) => dispatch({ type: "transcript.scrolled", sessionId: selected.id, scrollTop: event.currentTarget.scrollTop })}>
                {selected.messages.map((message) => (
                  <article className={`message ${message.role}`} key={message.id} aria-label={`${message.role} message`}>
                    <div className="message-meta">
                      <strong>{message.role === "user" ? "You" : "Harness"}</strong>
                      <span>{message.phase}</span>
                    </div>
                    <p>{message.content || "Waiting for output…"}</p>
                  </article>
                ))}
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

              {fixture ? <details className="playback-strip" aria-label="Fixture playback controls">
                <summary>Fixture playback · {remainingSteps} queued events</summary>
                <div className="playback-body">
                <div>
                  <strong>Deterministic fixture</strong>
                  <span>{remainingSteps} queued event{remainingSteps === 1 ? "" : "s"}</span>
                  <small>{bridgeProbe.label}</small>
                </div>
                <button type="button" disabled={!mutationsAllowed} onClick={() => void advance()}>Advance fixture</button>
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
                  <label className="visually-hidden" htmlFor="message-input">Message for {selected.title}</label>
                  <textarea
                    id="message-input"
                    rows={2}
                    value={state.local.drafts[selected.id] ?? ""}
                    placeholder={state.remote.source.kind === "fixture" ? "Type a fixture prompt…" : "Read-only live connection"}
                    disabled={state.remote.source.kind === "live"}
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
                    <button type="button" className="icon-button" aria-label="Attach file unavailable" title="Attachments are unavailable" disabled>＋</button>
                    <span className="permission-label">◉ {state.remote.source.kind === "fixture" ? "Fixture access" : "Read-only"}</span>
                    <p className="visually-hidden" role="status">{notice}</p>
                    <button type="button" className="effort-selector" title="Model and effort selection require a backend" disabled>No model · Effort unavailable ⌄</button>
                    <button
                      className="composer-submit"
                      type={selected.status === "running" ? "button" : "submit"}
                      aria-label={selected.status === "running" ? "Interrupt" : "Send"}
                      title={selected.status === "running" ? "Stop execution" : "Send (Ctrl+Enter)"}
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
            <div className="empty-state">No Session is available.</div>
          )}
        </section>

        {environmentOpen && selected ? <aside className="environment-popover" aria-label="Environment summary">
          <header><span>Environment</span><button type="button" className="icon-close" aria-label="Close environment" onClick={() => setEnvironmentOpen(false)}><UiIcon name="close" /></button></header>
          {hasCapability(state, "workspace") ? <EnvironmentPanel state={state} session={selected} /> : <UnavailablePanel label="workspace capability (missing, unavailable or incompatible)" />}
          <div className="environment-links">
            <button type="button" disabled={!changesAvailable || !selected.changeSet?.files.length} onClick={() => { const id = selected.changeSet?.files[0]?.documentId; if (id) openReview(id); }}>Changes →</button>
            <button type="button" disabled={!hasCapability(state, "agents")} onClick={() => { setEnvironmentOpen(false); dispatch({ type: "dock.opened", tab: "agents" }); }}>Subagents →</button>
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
  readonly onUnavailable: () => void;
}

function Sidebar({ state, bridgeProbe, onSelect, onToggleWorkspace, onUnavailable }: SidebarProps) {
  return (
    <aside className="session-rail" aria-label="Workspace and Session navigation">
      <div className="brand-row">
        <span className="brand-name"><strong>HarnessGUI</strong><UiIcon name="chevron-down" /></span>
        <button className="brand-search" type="button" aria-label="Search unavailable" title="Search is unavailable in the offline fixture" disabled><UiIcon name="search" /></button>
      </div>
      <button className="new-session" type="button" onClick={onUnavailable}>
        <UiIcon name="new-session" /> New Session <kbd aria-hidden="true">+</kbd>
      </button>
      <nav className="sidebar-shortcuts" aria-label="Application shortcuts">
        <button type="button" disabled title="Pull requests are unavailable in the offline fixture"><UiIcon name="pull-request" /><span>Pull requests</span></button>
        <button type="button" disabled title="Scheduling is unavailable in the offline fixture"><UiIcon name="scheduled" /><span>Scheduled</span></button>
        <button type="button" disabled title="Plugins are unavailable in the offline fixture"><UiIcon name="plugins" /><span>Plugins</span></button>
      </nav>
      <div className="fixture-banner"><span className="fixture-dot" />{state.remote.source.kind === "fixture" ? "Fixture data · no backend" : "Live AppHost · read-only"}</div>

      <nav className="workspace-scroll" aria-label="Workspaces">
        {!hasCapability(state, "workspace") ? <>
          <UnavailablePanel label="workspace capability (missing, unavailable or incompatible)" />
          {state.remote.sessionOrder.map((id) => <SessionButton key={id} session={state.remote.sessions[id]}
            selected={id === state.local.selectedSessionId} unread={Boolean(state.local.unread[id])} onSelect={() => onSelect(id)} />)}
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
          <p className="section-label">Recent</p>
          {state.remote.recentSessionIds.map((sessionId) => {
            const session = state.remote.sessions[sessionId];
            return session ? (
              <button className="recent-session" type="button" key={sessionId} onClick={() => onSelect(sessionId)}>
                <span>{session.title}</span><StatusMark status={session.status} />
              </button>
            ) : null;
          })}
        </section>
      </nav>

      <div className="rail-footer">
        <div className="user-avatar" aria-hidden="true">Z</div>
        <div><strong>zhnt</strong><span title={state.remote.source.kind === "fixture" ? bridgeProbe.label : state.remote.source.serviceInstanceId}>{state.remote.source.kind === "fixture" ? "Offline fixture" : "Live · read-only"}</span></div>
        <span aria-hidden="true">⋯</span>
      </div>
    </aside>
  );
}

function VcsBadge({ workspace }: { readonly workspace: WorkspaceSummary }) {
  if (!workspace.vcs) return <span className="vcs-badge none">plain</span>;
  return <span className={`vcs-badge ${workspace.vcs.kind}`}>{workspace.vcs.kind} · {workspace.vcs.label}</span>;
}

function SessionButton({ session, selected, unread, onSelect }: {
  readonly session: SessionSnapshot;
  readonly selected: boolean;
  readonly unread: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      className={`session-item${selected ? " selected" : ""}`}
      type="button"
      aria-current={selected ? "page" : undefined}
      aria-label={`${session.title} · ${statusLabel(session.status)}`}
      onClick={onSelect}
    >
      <span className="session-title">{session.title}</span>
      <StatusMark status={session.status} />
      {unread ? <span className="unread-dot" aria-label="Unread updates" /> : null}
    </button>
  );
}

function StatusMark({ status }: { readonly status: SessionSnapshot["status"] }) {
  return (
    <span className={`status-mark ${status}`} title={statusLabel(status)}>
      <span className="status-glyph" aria-hidden="true">{status === "running" ? "◌" : status === "waiting" ? "!" : status === "failed" ? "×" : ""}</span>
      <span className="sr-only">{statusLabel(status)}</span>
    </span>
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
  const currentWorkspace = session.context.project;
  return (
    <header className="conversation-header">
      <div className="session-heading">
        <UiIcon name="folder" />
        <div><h1>{session.title}</h1><p>{currentWorkspace} · {session.context.muxId}</p></div>
        <button type="button" aria-label="Session actions">•••</button>
      </div>
      <div className="header-actions">
        <span className={`connection-chip ${connection}`}>{connectionLabel(connection)}</span>
        <button type="button" aria-label="Share unavailable" disabled>⇧ Share</button>
        <button type="button" aria-label="Toggle environment" title="Environment" aria-pressed={environmentOpen} onClick={onEnvironment}><PanelIcon side="environment" /></button>
        <button type="button" aria-label="Bottom panel unavailable" title="Bottom panel unavailable in this fixture" disabled><PanelIcon side="bottom" /></button>
        <button type="button" aria-label="Open Work Dock" title="Toggle right panel" aria-pressed={dockOpen} onClick={onOpenDock}><PanelIcon side="right" /></button>
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
  const failures = run.activities.filter((activity) => activity.status === "failed").length;
  return (
    <section className="run-activity" aria-label="Run activity">
      <button className="activity-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <span className={`run-indicator ${run.status}`} aria-hidden="true">◌</span>
        <span><strong>{run.title}</strong><small>{run.activities.length} activities · {failures} failures</small></span>
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
              <span>{activity.durationLabel ?? activity.status}</span>
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
  const currentIndex = run.currentTaskId ? run.tasks.findIndex((task) => task.id === run.currentTaskId) : -1;
  const completed = run.tasks.filter((task) => task.status === "completed").length;
  const label = currentIndex >= 0 ? `Step ${currentIndex + 1} / ${run.tasks.length}` : `${completed} / ${run.tasks.length} complete`;
  return (
    <div className="task-progress-wrap">
      {open ? (
        <div className="task-popover" aria-label="Run tasks">
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
  return (
    <section className="change-card" aria-label="Fixture changes">
      <header>
        <span className="change-icon" aria-hidden="true">▣</span>
        <div><strong>Edited {changeSet.files.length} files</strong><small>{changeSet.scopeLabel}</small></div>
        <span className="additions">+{changeSet.additions}</span><span className="deletions">-{changeSet.deletions}</span>
        <button type="button" onClick={onOpenReview}>Review</button>
      </header>
      <div className="change-files">
        {changeSet.files.map((file) => (
          <button type="button" key={file.id} onClick={(event) => onOpenFile(file.documentId, event.currentTarget)}>
            <span>{file.path}</span><span className="additions">+{file.additions}</span><span className="deletions">-{file.deletions}</span>
          </button>
        ))}
      </div>
      <footer><code>{changeSet.revision}</code><span>Read-only fixture · repository actions unavailable</span></footer>
    </section>
  );
}

function QuickLook({ document, onClose, onOpenReview }: {
  readonly document: ReadonlyDocument;
  readonly onClose: () => void;
  readonly onOpenReview: () => void;
}) {
  return (
    <aside className="quick-look" aria-label={`Quick look ${document.title}`}>
      <header><strong>{document.title}</strong><button type="button" className="icon-close" onClick={onClose} aria-label="Close quick look"><UiIcon name="close" /></button></header>
      <DocumentView document={document} compact />
      <footer><button type="button" onClick={onOpenReview}>Open full review →</button></footer>
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
  const { state, session, selectedDocument, onClose, onTab, onSelectDocument, onSelectTask, onSelectAgent } = props;
  const facet = state.local.dockTab === "environment" ? "workspace" : state.local.dockTab === "review" ? "changes" : state.local.dockTab;
  const available = hasCapability(state, facet);
  const visibleRun = session.run ? {
    ...session.run,
    tasks: hasCapability(state, "tasks") ? session.run.tasks : [],
    agentRuns: hasCapability(state, "agents") ? session.run.agentRuns : [],
  } : null;
  return (
    <aside className={`work-dock${state.local.dockTab === "environment" ? " environment-card" : ""}`} aria-label="Work Dock">
      <header className="dock-header">
        <strong>{dockTabs.find((tab) => tab.id === state.local.dockTab)?.label}</strong>
        <button type="button" className="icon-close" onClick={onClose} aria-label="Close Work Dock"><UiIcon name="close" /></button>
      </header>
      <nav className="dock-tabs" aria-label="Work Dock panels">
        {dockTabs.filter((tab) => tab.id !== "environment").map((tab) => (
          <button type="button" key={tab.id} aria-pressed={state.local.dockTab === tab.id} onClick={() => onTab(tab.id)}>
            <span aria-hidden="true">{tab.glyph}</span><span>{tab.label}</span>
          </button>
        ))}
      </nav>
      <div className="dock-content">
        {!available ? <UnavailablePanel label={`${facet} capability (missing, unavailable or incompatible)`} /> : <>
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
  const workspace = state.remote.workspaces[session.workspaceId];
  return (
    <section className="panel-stack" aria-label="Environment details">
      <p className="fixture-panel-label">Fixture projection</p>
      <dl className="detail-list">
        <div><dt>Workspace</dt><dd>{workspace?.title ?? "Unavailable"}</dd></div>
        <div><dt>Root</dt><dd>{workspace?.rootLabel ?? session.context.rootLabel}</dd></div>
        <div><dt>Version control</dt><dd>{workspace?.vcs ? `${workspace.vcs.kind} · ${workspace.vcs.label}` : "None"}</dd></div>
        <div><dt>Application</dt><dd>{session.context.applicationId}</dd></div>
        <div><dt>Mux / member</dt><dd>{session.context.muxId} / {session.context.memberId}</dd></div>
        <div><dt>Session</dt><dd>{session.context.sessionId}</dd></div>
        <div><dt>Generation</dt><dd>{state.remote.generation}</dd></div>
      </dl>
      <h2>Capabilities</h2>
      <div className="capability-list">
        {state.remote.capabilities.map((capability) => (
          <span className={`capability ${capability.availability}`} key={capability.name}>
            {capability.name} · {capability.version ?? "unavailable"}
          </span>
        ))}
      </div>
    </section>
  );
}

function TasksPanel({ run, selectedTaskId, onSelectTask, onSelectAgent }: {
  readonly run: RunProjection | null;
  readonly selectedTaskId: string | null;
  readonly onSelectTask: (taskId: string) => void;
  readonly onSelectAgent: (agentRunId: string) => void;
}) {
  if (!run) return <UnavailablePanel label="Task projection" />;
  const selected = run.tasks.find((task) => task.id === selectedTaskId) ?? run.tasks[0];
  return (
    <section className="panel-stack" aria-label="Task details">
      <p className="fixture-panel-label">{run.status} · {run.tasks.length} Tasks</p>
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
  const activities = run.activities.filter((activity) => task.activityIds.includes(activity.id));
  return (
    <article className="selection-detail">
      <span className={`detail-status ${task.status}`}>{task.status}</span>
      <h2>{task.title}</h2>
      <p>{activities.length} projected activities</p>
      <h3>Assigned AgentRuns</h3>
      {task.assignedAgentRunIds.map((agentRunId) => {
        const agent = run.agentRuns.find((item) => item.id === agentRunId);
        return agent ? <button type="button" key={agent.id} onClick={() => onSelectAgent(agent.id)}>Open {agent.label} →</button> : null;
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
  if (!run) return <UnavailablePanel label="AgentRun projection" />;
  const selected = run.agentRuns.find((agent) => agent.id === selectedAgentRunId) ?? run.agentRuns[0];
  return (
    <section className="panel-stack" aria-label="AgentRun details">
      <p className="fixture-panel-label">{run.agentRuns.length} AgentRuns · identities remain separate from Tasks</p>
      <div className="agent-tree">
        {run.agentRuns.map((agent) => (
          <button type="button" key={agent.id} className={agent.id === selected?.id ? "selected" : ""} onClick={() => onSelectAgent(agent.id)}>
            <span className={`agent-avatar ${agent.role}`} aria-hidden="true">{agent.role === "root" ? "H" : "R"}</span>
            <span><strong>{agent.label}</strong><small>{agent.role} · {agent.status}</small></span>
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
  return (
    <article className="selection-detail">
      <span className={`detail-status ${agent.status}`}>{agent.status}</span>
      <h2>{agent.label}</h2><p>{agent.summary ?? "No fixture summary."}</p>
      <h3>Assigned Tasks</h3>
      {agent.taskIds.map((taskId) => {
        const task = run.tasks.find((item) => item.id === taskId);
        return task ? <button type="button" key={task.id} onClick={() => onSelectTask(task.id)}>Open {task.title} →</button> : null;
      })}
    </article>
  );
}

function ReviewPanel({ session, selectedDocument, onSelectDocument }: {
  readonly session: SessionSnapshot;
  readonly selectedDocument: ReadonlyDocument | undefined;
  readonly onSelectDocument: (documentId: string) => void;
}) {
  const changeDocuments = session.changeSet?.files
    .map((file) => session.documents.find((document) => document.id === file.documentId))
    .filter((document): document is ReadonlyDocument => Boolean(document)) ?? [];
  if (!session.changeSet) return <UnavailablePanel label="ChangeSet projection" />;
  const visibleDocument = selectedDocument?.kind === "diff" ? selectedDocument : changeDocuments[0];
  return (
    <section className="review-panel" aria-label="Read-only review">
      <header>
        <div><strong>{session.changeSet.scopeLabel}</strong><span><b>+{session.changeSet.additions}</b> <em>-{session.changeSet.deletions}</em></span></div>
        <button type="button" disabled>Commit or push</button>
      </header>
      <div className="review-files">
        {changeDocuments.map((document) => (
          <button type="button" key={document.id} className={document.id === visibleDocument?.id ? "selected" : ""} onClick={() => onSelectDocument(document.id)}>{document.title}</button>
        ))}
      </div>
      {visibleDocument ? <DocumentView document={visibleDocument} /> : <p>No Diff fixture is available.</p>}
    </section>
  );
}

function UnavailablePanel({ label }: { readonly label: string }) {
  return <div className="unavailable-panel"><strong>{label} unavailable</strong><p>This Session has no accepted value. The GUI does not infer one from transcript text.</p></div>;
}

function DocumentView({ document, compact = false }: { readonly document: ReadonlyDocument; readonly compact?: boolean }) {
  const lines = document.content.split("\n");
  return (
    <article className={`document-view${compact ? " compact" : ""}`} aria-label={document.title}>
      <header><span>{document.kind}</span><code>{document.revision}</code></header>
      <p className="document-source">{document.sourceLabel}</p>
      <pre>{lines.map((line, index) => <span className={diffLineClass(document, line)} key={`${index}-${line}`}>{line || " "}{index < lines.length - 1 ? "\n" : ""}</span>)}</pre>
    </article>
  );
}

function TaskStatusGlyph({ status }: { readonly status: TaskProjection["status"] }) {
  const glyph = status === "completed" ? "✓" : status === "running" ? "◌" : status === "failed" ? "×" : status === "cancelled" ? "–" : "○";
  return <span className={`task-status ${status}`} aria-label={status}>{glyph}</span>;
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

function statusLabel(status: SessionSnapshot["status"]): string {
  return { idle: "Idle", running: "Running", waiting: "Needs input", interrupted: "Interrupted", failed: "Failed" }[status];
}

function connectionLabel(connection: string): string {
  return { "fixture-offline": "Offline fixture", connected: "Connected", disconnected: "Disconnected", "resync-required": "Resync required" }[connection] ?? connection;
}

function App() {
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
  return client ? <HarnessGui client={client} /> : <div className="empty-state">Opening HarnessGUI…</div>;
}

export default App;
