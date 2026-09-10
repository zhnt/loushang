import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import "./App.css";
import { createMockAppClient } from "./client/mockAppClient";
import { probeFixtureBridge, type BridgeProbe } from "./client/nativeFixtureBridge";
import type {
  AgentRunProjection,
  ChangeSetProjection,
  FixturePlaybackPort,
  ReadonlyDocument,
  RunProjection,
  SessionSnapshot,
  TaskProjection,
  WorkspaceSummary,
} from "./client/model";
import { emptyGuiState, guiReducer, type DockTab, type GuiState } from "./client/state";

interface HarnessGuiProps {
  readonly client: FixturePlaybackPort;
}

const dockTabs: readonly { id: DockTab; label: string; glyph: string }[] = [
  { id: "environment", label: "Environment", glyph: "◎" },
  { id: "tasks", label: "Tasks", glyph: "☷" },
  { id: "agents", label: "Subagents", glyph: "✣" },
  { id: "review", label: "Review", glyph: "▣" },
];

export function HarnessGui({ client }: HarnessGuiProps) {
  const [state, dispatch] = useReducer(guiReducer, undefined, emptyGuiState);
  const [notice, setNotice] = useState("Loading fixture snapshot…");
  const [remainingSteps, setRemainingSteps] = useState(client.remainingFixtureSteps());
  const [bridgeProbe, setBridgeProbe] = useState<BridgeProbe>({
    status: "web-mock",
    label: "Web Mock",
  });
  const submissionCounter = useRef(1);
  const quickLookTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreQuickLookFocusRef = useRef(false);

  useEffect(() => {
    let active = true;
    const unsubscribe = client.subscribe((event) => {
      dispatch({ type: "event.received", event });
      setRemainingSteps(client.remainingFixtureSteps());
    });
    void client.snapshot().then((snapshot) => {
      if (!active) return;
      dispatch({ type: "snapshot.installed", snapshot });
      setRemainingSteps(client.remainingFixtureSteps());
      setNotice("Fixture snapshot installed. No backend is running.");
    });
    void probeFixtureBridge().then((probe) => {
      if (active) setBridgeProbe(probe);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [client]);

  useEffect(() => {
    if (!state.local.quickLookDocumentId && restoreQuickLookFocusRef.current) {
      restoreQuickLookFocusRef.current = false;
      quickLookTriggerRef.current?.focus();
    }
  }, [state.local.quickLookDocumentId]);

  const selectedId = state.local.selectedSessionId;
  const selected = selectedId ? state.remote.sessions[selectedId] : undefined;
  const selectedDocument = selected
    ? findSelectedDocument(selected, state.local.selectedDocuments[selected.id] ?? null)
    : undefined;
  const quickLookDocument = selected?.documents.find(
    (document) => document.id === state.local.quickLookDocumentId,
  );

  async function submit(): Promise<void> {
    if (!selected) return;
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
    setRemainingSteps(client.remainingFixtureSteps());
    setNotice("Fixture accepted the prompt. Advance it step by step.");
  }

  async function advance(): Promise<void> {
    const step = await client.advanceFixture();
    if (!step) {
      setNotice("No fixture event is waiting.");
      return;
    }
    setRemainingSteps(step.remaining);
    setNotice(`Playback: ${step.label}.`);
  }

  async function interrupt(): Promise<void> {
    if (!selected) return;
    const receipt = await client.interrupt(selected.id);
    setRemainingSteps(client.remainingFixtureSteps());
    setNotice(
      receipt.accepted
        ? "Fixture execution interrupted."
        : (receipt.reason ?? "Interrupt was not accepted."),
    );
  }

  function openReview(documentId: string): void {
    if (!selected) return;
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
      <NativeFrame />
      <main className={`app-shell${state.local.dockOpen ? "" : " dock-closed"}`}>
        <Sidebar
          state={state}
          bridgeProbe={bridgeProbe}
          onSelect={(sessionId) => dispatch({ type: "session.selected", sessionId })}
          onToggleWorkspace={(workspaceId) => dispatch({ type: "workspace.toggled", workspaceId })}
          onUnavailable={() => setNotice("New Session is unavailable in the offline fixture.")}
        />

        <section className="conversation-pane" aria-label="Session workspace">
          {selected ? (
            <>
              <SessionHeader
                session={selected}
                connection={state.remote.connection}
                dockOpen={state.local.dockOpen}
                onOpenDock={() => dispatch({ type: "dock.opened", tab: state.local.dockTab })}
              />
              {state.diagnostic ? <div className="diagnostic" role="alert">{state.diagnostic}</div> : null}
              <div className="transcript" aria-live="polite">
                {selected.messages.map((message) => (
                  <article className={`message ${message.role}`} key={message.id} aria-label={`${message.role} message`}>
                    <div className="message-meta">
                      <strong>{message.role === "user" ? "You" : "Harness"}</strong>
                      <span>{message.phase}</span>
                    </div>
                    <p>{message.content || "Waiting for fixture output…"}</p>
                  </article>
                ))}
                {selected.run ? (
                  <RunActivity
                    run={selected.run}
                    expanded={Boolean(state.local.expandedActivities[selected.run.id])}
                    onToggle={() => dispatch({ type: "activity.toggled", activityGroupId: selected.run!.id })}
                    onSelectTask={(taskId) => dispatch({ type: "task.selected", taskId })}
                  />
                ) : null}
                {selected.changeSet ? (
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

              {quickLookDocument ? (
                <QuickLook
                  document={quickLookDocument}
                  onClose={closeQuickLook}
                  onOpenReview={() => openReview(quickLookDocument.id)}
                />
              ) : null}

              <div className="playback-strip" aria-label="Fixture playback controls">
                <div>
                  <strong>Deterministic fixture</strong>
                  <span>{remainingSteps} queued event{remainingSteps === 1 ? "" : "s"}</span>
                </div>
                <button type="button" onClick={() => void advance()}>Advance fixture</button>
              </div>

              <div className="composer-stack">
                {selected.run ? (
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
                  <label htmlFor="message-input">Message for {selected.title}</label>
                  <textarea
                    id="message-input"
                    rows={3}
                    value={state.local.drafts[selected.id] ?? ""}
                    placeholder="Type a fixture prompt…"
                    onChange={(event) =>
                      dispatch({ type: "draft.changed", sessionId: selected.id, value: event.currentTarget.value })
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                        event.preventDefault();
                        void submit();
                      }
                    }}
                  />
                  <div className="composer-actions">
                    <button type="button" className="icon-button" aria-label="Attach fixture file">＋</button>
                    <span className="permission-label">◉ Fixture access</span>
                    <p role="status">{notice}</p>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={selected.status !== "running"}
                      onClick={() => void interrupt()}
                    >
                      Interrupt
                    </button>
                    <button className="primary-button" type="submit" disabled={selected.status === "running"}>
                      Send
                    </button>
                  </div>
                </form>
              </div>
            </>
          ) : (
            <div className="empty-state">No fixture Session is available.</div>
          )}
        </section>

        {state.local.dockOpen && selected ? (
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

function NativeFrame() {
  return (
    <header className="native-frame" aria-label="Application menu">
      <span className="window-glyph">▱</span>
      <span className="history-glyph" aria-hidden="true">←</span>
      <span className="history-glyph muted" aria-hidden="true">→</span>
      <nav aria-label="Main menu">
        <span>File</span><span>Edit</span><span>View</span><span>Help</span>
      </nav>
      <div className="window-controls" aria-hidden="true"><span>—</span><span>□</span><span>×</span></div>
    </header>
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
        <strong>HarnessGUI</strong><span aria-hidden="true">⌄</span>
        <span className="brand-tools" aria-hidden="true">⌕　♢</span>
      </div>
      <button className="new-session" type="button" onClick={onUnavailable}>
        <span aria-hidden="true">□＋</span> New Session <kbd>+</kbd>
      </button>
      <div className="fixture-banner"><span className="fixture-dot" />Fixture data · no backend</div>

      <nav className="workspace-scroll" aria-label="Workspaces">
        {state.remote.workspaceOrder.map((workspaceId) => {
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
                <span className="folder-glyph" aria-hidden="true">▱</span>
                <span>{workspace.title}</span>
                <VcsBadge workspace={workspace} />
                <span aria-hidden="true">{expanded ? "⌃" : "⌄"}</span>
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
        <div><strong>zhnt</strong><span>{bridgeProbe.label} · fixture</span></div>
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

function SessionHeader({ session, connection, dockOpen, onOpenDock }: {
  readonly session: SessionSnapshot;
  readonly connection: string;
  readonly dockOpen: boolean;
  readonly onOpenDock: () => void;
}) {
  const currentWorkspace = session.context.project;
  return (
    <header className="conversation-header">
      <div className="session-heading">
        <span aria-hidden="true">▱</span>
        <div><h1>{session.title}</h1><p>{currentWorkspace} · {session.context.muxId}</p></div>
        <button type="button" aria-label="Session actions">•••</button>
      </div>
      <div className="header-actions">
        <span className={`connection-chip ${connection}`}>{connectionLabel(connection)}</span>
        <button type="button" aria-label="Share unavailable" disabled>⇧ Share</button>
        <button type="button" aria-label="Open Work Dock" aria-pressed={dockOpen} onClick={onOpenDock}>▥</button>
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
      <header><strong>{document.title}</strong><button type="button" onClick={onClose} aria-label="Close quick look">×</button></header>
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
  return (
    <aside className="work-dock" aria-label="Work Dock">
      <header className="dock-header">
        <strong>{dockTabs.find((tab) => tab.id === state.local.dockTab)?.label}</strong>
        <button type="button" onClick={onClose} aria-label="Close Work Dock">×</button>
      </header>
      <nav className="dock-tabs" aria-label="Work Dock panels">
        {dockTabs.map((tab) => (
          <button type="button" key={tab.id} aria-pressed={state.local.dockTab === tab.id} onClick={() => onTab(tab.id)}>
            <span aria-hidden="true">{tab.glyph}</span><span>{tab.label}</span>
          </button>
        ))}
      </nav>
      <div className="dock-content">
        {state.local.dockTab === "environment" ? <EnvironmentPanel state={state} session={session} /> : null}
        {state.local.dockTab === "tasks" ? (
          <TasksPanel run={session.run} selectedTaskId={state.local.selectedTaskId} onSelectTask={onSelectTask} onSelectAgent={onSelectAgent} />
        ) : null}
        {state.local.dockTab === "agents" ? (
          <AgentsPanel run={session.run} selectedAgentRunId={state.local.selectedAgentRunId} onSelectAgent={onSelectAgent} onSelectTask={onSelectTask} />
        ) : null}
        {state.local.dockTab === "review" ? (
          <ReviewPanel session={session} selectedDocument={selectedDocument} onSelectDocument={onSelectDocument} />
        ) : null}
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
  return <div className="unavailable-panel"><strong>{label} unavailable</strong><p>This Session has no accepted fixture value. The GUI does not infer one from transcript text.</p></div>;
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
  const client = useMemo(() => createMockAppClient(), []);
  return <HarnessGui client={client} />;
}

export default App;
