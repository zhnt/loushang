import type {
  ClientEvent,
  ClientSnapshot,
  ConnectionState,
  ReadonlyDocument,
  SessionSnapshot,
  WorkspaceSummary,
} from "./model";

export type DockTab = "environment" | "tasks" | "agents" | "review";

type SessionView = Pick<LocalState, "selectedTaskId" | "selectedAgentRunId" | "dockTab" | "dockOpen" | "taskListOpen" | "transcriptScrollTop">;

function viewKey(session: SessionSnapshot): string {
  const context = session.context;
  return JSON.stringify([session.workspaceId, context.project, context.rootLabel,
    context.applicationId, context.muxId, context.memberId, context.sessionId, context.source, session.id]);
}

function sessionView(session: SessionSnapshot, previous?: SessionView): SessionView {
  return {
    transcriptScrollTop: previous?.transcriptScrollTop ?? 0,
    dockTab: previous?.dockTab ?? "environment",
    dockOpen: previous?.dockOpen ?? true,
    taskListOpen: previous?.taskListOpen ?? false,
    selectedTaskId: session.run?.tasks.some((task) => task.id === previous?.selectedTaskId)
      ? previous!.selectedTaskId : session.run?.currentTaskId ?? null,
    selectedAgentRunId: session.run?.agentRuns.some((agent) => agent.id === previous?.selectedAgentRunId)
      ? previous!.selectedAgentRunId : session.run?.agentRuns[0]?.id ?? null,
  };
}

export function hasCapability(state: GuiState, name: ClientSnapshot["capabilities"][number]["name"]): boolean {
  const expected = state.remote.source.kind === "fixture"
    ? (name === "workspace" || name === "changes" ? "fixture/v2" : "fixture/v1")
    : ({
        workspace: "loushang.workspace/v1",
        changes: "loushang.changes/v1",
        artifacts: "loushang.artifacts/v1",
        tasks: "loushang.execution/v1",
        agents: "loushang.execution/v1",
      } as const)[name];
  return state.remote.capabilities.some((item) =>
    item.name === name && item.availability === state.remote.source.kind && item.version === expected,
  );
}

export interface RemoteState {
  readonly generation: string;
  readonly connection: ConnectionState;
  readonly source: ClientSnapshot["source"];
  readonly capabilities: ClientSnapshot["capabilities"];
  readonly workspaces: Readonly<Record<string, WorkspaceSummary>>;
  readonly workspaceOrder: readonly string[];
  readonly sessions: Readonly<Record<string, SessionSnapshot>>;
  readonly sessionOrder: readonly string[];
  readonly recentSessionIds: readonly string[];
}

export interface LocalState {
  readonly transcriptScrollTop: number;
  readonly sessionViews: Readonly<Record<string, SessionView>>;
  readonly selectedSessionId: string | null;
  readonly drafts: Readonly<Record<string, string>>;
  readonly selectedDocuments: Readonly<Record<string, string | null>>;
  readonly unread: Readonly<Record<string, boolean>>;
  readonly expandedWorkspaces: Readonly<Record<string, boolean>>;
  readonly expandedActivities: Readonly<Record<string, boolean>>;
  readonly selectedTaskId: string | null;
  readonly selectedAgentRunId: string | null;
  readonly dockTab: DockTab;
  readonly dockOpen: boolean;
  readonly taskListOpen: boolean;
  readonly quickLookDocumentId: string | null;
}

export interface GuiState {
  readonly remote: RemoteState;
  readonly local: LocalState;
  readonly diagnostic: string | null;
}

export type GuiAction =
  | { readonly type: "sync.failed"; readonly message: string }
  | { readonly type: "transcript.scrolled"; readonly sessionId: string; readonly scrollTop: number }
  | { readonly type: "snapshot.installed"; readonly snapshot: ClientSnapshot }
  | { readonly type: "session.selected"; readonly sessionId: string }
  | { readonly type: "workspace.toggled"; readonly workspaceId: string }
  | { readonly type: "activity.toggled"; readonly activityGroupId: string }
  | { readonly type: "task-list.toggled" }
  | { readonly type: "dock.closed" }
  | { readonly type: "dock.opened"; readonly tab: DockTab }
  | { readonly type: "task.selected"; readonly taskId: string }
  | { readonly type: "agent.selected"; readonly agentRunId: string }
  | { readonly type: "quick-look.opened"; readonly documentId: string }
  | { readonly type: "quick-look.closed" }
  | {
      readonly type: "draft.changed";
      readonly sessionId: string;
      readonly value: string;
    }
  | {
      readonly type: "document.selected";
      readonly sessionId: string;
      readonly documentId: string;
    }
  | { readonly type: "event.received"; readonly event: ClientEvent };

export function emptyGuiState(): GuiState {
  return {
    remote: {
      generation: "",
      connection: "disconnected",
      source: { kind: "fixture", label: "Fixture not loaded" },
      capabilities: [],
      workspaces: {},
      workspaceOrder: [],
      sessions: {},
      sessionOrder: [],
      recentSessionIds: [],
    },
    local: {
      transcriptScrollTop: 0,
      sessionViews: {},
      selectedSessionId: null,
      drafts: {},
      selectedDocuments: {},
      unread: {},
      expandedWorkspaces: {},
      expandedActivities: {},
      selectedTaskId: null,
      selectedAgentRunId: null,
      dockTab: "environment",
      dockOpen: true,
      taskListOpen: false,
      quickLookDocumentId: null,
    },
    diagnostic: null,
  };
}

export function guiReducer(state: GuiState, action: GuiAction): GuiState {
  switch (action.type) {
    case "sync.failed":
      return requireResync(state, action.message);
    case "transcript.scrolled":
      if (action.sessionId !== state.local.selectedSessionId || !Number.isFinite(action.scrollTop)) return state;
      return { ...state, local: { ...state.local, transcriptScrollTop: Math.max(0, action.scrollTop) } };
    case "snapshot.installed":
      return installSnapshot(state, action.snapshot);
    case "session.selected": {
      const session = state.remote.sessions[action.sessionId];
      if (!session) return state;
      if (state.local.selectedSessionId === action.sessionId) return state;
      const previous = state.local.selectedSessionId ? state.remote.sessions[state.local.selectedSessionId] : undefined;
      const views = { ...state.local.sessionViews };
      if (previous) views[viewKey(previous)] = sessionView(previous, state.local);
      return {
        ...state,
        local: {
          ...state.local,
          ...sessionView(session, views[viewKey(session)]),
          sessionViews: views,
          selectedSessionId: action.sessionId,
          quickLookDocumentId: null,
          unread: { ...state.local.unread, [action.sessionId]: false },
        },
      };
    }
    case "workspace.toggled":
      if (!state.remote.workspaces[action.workspaceId]) return state;
      return {
        ...state,
        local: {
          ...state.local,
          expandedWorkspaces: {
            ...state.local.expandedWorkspaces,
            [action.workspaceId]: !state.local.expandedWorkspaces[action.workspaceId],
          },
        },
      };
    case "activity.toggled":
      return {
        ...state,
        local: {
          ...state.local,
          expandedActivities: {
            ...state.local.expandedActivities,
            [action.activityGroupId]: !state.local.expandedActivities[action.activityGroupId],
          },
        },
      };
    case "task-list.toggled":
      return { ...state, local: { ...state.local, taskListOpen: !state.local.taskListOpen } };
    case "dock.closed":
      return { ...state, local: { ...state.local, dockOpen: false } };
    case "dock.opened":
      return {
        ...state,
        local: { ...state.local, dockOpen: true, dockTab: action.tab },
      };
    case "task.selected":
      return {
        ...state,
        local: {
          ...state.local,
          selectedTaskId: action.taskId,
          dockOpen: true,
          dockTab: "tasks",
          taskListOpen: false,
        },
      };
    case "agent.selected":
      return {
        ...state,
        local: {
          ...state.local,
          selectedAgentRunId: action.agentRunId,
          dockOpen: true,
          dockTab: "agents",
        },
      };
    case "quick-look.opened":
      return {
        ...state,
        local: { ...state.local, quickLookDocumentId: action.documentId },
      };
    case "quick-look.closed":
      return { ...state, local: { ...state.local, quickLookDocumentId: null } };
    case "draft.changed":
      return {
        ...state,
        local: {
          ...state.local,
          drafts: { ...state.local.drafts, [action.sessionId]: action.value },
        },
      };
    case "document.selected":
      return {
        ...state,
        local: {
          ...state.local,
          selectedDocuments: {
            ...state.local.selectedDocuments,
            [action.sessionId]: action.documentId,
          },
        },
      };
    case "event.received":
      return applyEvent(state, action.event);
  }
}

function installSnapshot(state: GuiState, snapshot: ClientSnapshot): GuiState {
  const workspaces = Object.fromEntries(
    snapshot.workspaces.map((workspace) => [workspace.id, workspace]),
  );
  const workspaceIds = snapshot.workspaces.map((workspace) => workspace.id);
  const sessions = Object.fromEntries(
    snapshot.sessions.map((session) => [session.id, session]),
  );
  const sessionIds = snapshot.sessions.map((session) => session.id);
  const drafts = retainKeys(state.local.drafts, sessionIds, "");
  const unread = retainKeys(state.local.unread, sessionIds, false);
  const expandedWorkspaces = Object.fromEntries(
    workspaceIds.map((workspaceId) => [
      workspaceId,
      state.local.expandedWorkspaces[workspaceId] ?? true,
    ]),
  );
  const selectedDocuments = Object.fromEntries(
    snapshot.sessions.map((session) => {
      const previous = state.local.selectedDocuments[session.id];
      const stillExists = session.documents.some((document) => document.id === previous);
      return [session.id, stillExists ? previous : (session.documents[0]?.id ?? null)];
    }),
  );
  const priorSelection = state.local.selectedSessionId;
  const selectedSessionId =
    priorSelection && sessions[priorSelection]
      ? priorSelection
      : sessions[snapshot.selectedSessionId]
        ? snapshot.selectedSessionId
        : (sessionIds[0] ?? null);
  const selectedSession = selectedSessionId ? sessions[selectedSessionId] : undefined;
  const views = { ...state.local.sessionViews };
  const previousSession = priorSelection ? state.remote.sessions[priorSelection] : undefined;
  if (previousSession) views[viewKey(previousSession)] = sessionView(previousSession, state.local);
  const retainedViews = Object.fromEntries(snapshot.sessions.flatMap((session) => {
    const key = viewKey(session);
    return views[key] ? [[key, sessionView(session, views[key])]] : [];
  }));

  return {
    remote: {
      generation: snapshot.generation,
      connection: snapshot.connection,
      source: snapshot.source,
      capabilities: snapshot.capabilities,
      workspaces,
      workspaceOrder: workspaceIds,
      sessions,
      sessionOrder: sessionIds,
      recentSessionIds: snapshot.recentSessionIds.filter((id) => Boolean(sessions[id])),
    },
    local: {
      ...state.local,
      ...(selectedSession ? sessionView(selectedSession, retainedViews[viewKey(selectedSession)]) : {}),
      sessionViews: retainedViews,
      selectedSessionId,
      drafts,
      selectedDocuments,
      unread,
      expandedWorkspaces,
      quickLookDocumentId: null,
    },
    diagnostic: null,
  };
}

function applyEvent(state: GuiState, event: ClientEvent): GuiState {
  // Only an authoritative snapshot can recover a disconnected or gapped stream.
  if (state.remote.connection === "disconnected" || state.remote.connection === "resync-required") {
    return state;
  }
  if (event.generation !== state.remote.generation) {
    return requireResync(state, `Ignored event ${event.id}: stale generation.`);
  }
  const session = state.remote.sessions[event.sessionId];
  if (!session) {
    return requireResync(state, `Ignored event ${event.id}: unknown session.`);
  }

  let currentCursor: bigint;
  let incomingCursor: bigint;
  try {
    currentCursor = BigInt(session.cursor);
    incomingCursor = BigInt(event.cursor);
  } catch {
    return requireResync(state, `Ignored event ${event.id}: invalid cursor.`);
  }
  if (incomingCursor <= currentCursor) return state;
  if (incomingCursor !== currentCursor + 1n) {
    return requireResync(state, `Ignored event ${event.id}: cursor gap.`);
  }

  const updated = reduceSession(session, event);
  const isInactive = state.local.selectedSessionId !== event.sessionId;
  return {
    ...state,
    remote: {
      ...state.remote,
      sessions: { ...state.remote.sessions, [event.sessionId]: updated },
    },
    local: {
      ...state.local,
      selectedTaskId:
        !isInactive && !updated.run?.tasks.some((task) => task.id === state.local.selectedTaskId)
          ? updated.run?.currentTaskId ?? null
          : state.local.selectedTaskId,
      unread: isInactive
        ? { ...state.local.unread, [event.sessionId]: true }
        : state.local.unread,
    },
    diagnostic: null,
  };
}

// Shared fixture projection fold: no UI-local state or service-side execution.
export function reduceSession(session: SessionSnapshot, event: ClientEvent): SessionSnapshot {
  switch (event.type) {
    case "execution.accepted":
      return {
        ...session,
        cursor: event.cursor,
        status: "running",
        run: event.run,
        messages: [...session.messages, event.userMessage, event.assistantMessage],
      };
    case "output.delta":
      return {
        ...session,
        cursor: event.cursor,
        messages: updateMessage(session, event.messageId, (message) => ({
          ...message,
          content: message.content + event.delta,
          phase: "streaming",
        })),
      };
    case "document.available":
      return {
        ...session,
        cursor: event.cursor,
        documents: replaceDocument(session.documents, event.document),
      };
    case "run.activity.appended":
      if (!session.run || session.run.id !== event.runId) return { ...session, cursor: event.cursor };
      return {
        ...session,
        cursor: event.cursor,
        run: {
          ...session.run,
          activities: [...session.run.activities, event.activity],
          tasks: session.run.tasks.map((task) =>
            task.id === event.activity.taskId
              ? { ...task, activityIds: [...task.activityIds, event.activity.id] }
              : task,
          ),
        },
      };
    case "run.tasks.updated":
      if (!session.run || session.run.id !== event.runId) return { ...session, cursor: event.cursor };
      return {
        ...session,
        cursor: event.cursor,
        run: {
          ...session.run,
          currentTaskId: event.currentTaskId,
          tasks: session.run.tasks.map((task) => {
            const update = event.updates.find((candidate) => candidate.taskId === task.id);
            return update ? { ...task, status: update.status } : task;
          }),
        },
      };
    case "run.agent.updated":
      if (!session.run || session.run.id !== event.runId) return { ...session, cursor: event.cursor };
      return {
        ...session,
        cursor: event.cursor,
        run: {
          ...session.run,
          agentRuns: session.run.agentRuns.map((agent) =>
            agent.id === event.agentRunId
              ? { ...agent, status: event.status, summary: event.summary ?? agent.summary }
              : agent,
          ),
        },
      };
    case "execution.completed":
      return {
        ...session,
        cursor: event.cursor,
        status: "idle",
        run: session.run
          ? {
              ...session.run,
              status: "completed",
              currentTaskId: null,
              tasks: session.run.tasks.map((task) =>
                task.status === "running" ? { ...task, status: "completed" } : task,
              ),
              agentRuns: session.run.agentRuns.map((agent) =>
                agent.status === "running" ? { ...agent, status: "completed" } : agent,
              ),
            }
          : null,
        messages: updateMessage(session, event.messageId, (message) => ({
          ...message,
          phase: "complete",
        })),
      };
    case "execution.interrupted":
      return {
        ...session,
        cursor: event.cursor,
        status: "interrupted",
        run: session.run
          ? {
              ...session.run,
              status: "interrupted",
              tasks: session.run.tasks.map((task) =>
                task.status === "running" ? { ...task, status: "cancelled" } : task,
              ),
              agentRuns: session.run.agentRuns.map((agent) =>
                agent.status === "running" ? { ...agent, status: "interrupted" } : agent,
              ),
            }
          : null,
        messages: updateMessage(session, event.messageId, (message) => ({
          ...message,
          phase: "interrupted",
        })),
      };
  }
}

function updateMessage(
  session: SessionSnapshot,
  messageId: string,
  update: (message: SessionSnapshot["messages"][number]) => SessionSnapshot["messages"][number],
): ReadonlyArray<SessionSnapshot["messages"][number]> {
  return session.messages.map((message) =>
    message.id === messageId ? update(message) : message,
  );
}

function replaceDocument(
  documents: readonly ReadonlyDocument[],
  incoming: ReadonlyDocument,
): readonly ReadonlyDocument[] {
  const existing = documents.findIndex((document) => document.id === incoming.id);
  if (existing < 0) return [...documents, incoming];
  return documents.map((document, index) => (index === existing ? incoming : document));
}

function requireResync(state: GuiState, diagnostic: string): GuiState {
  return {
    ...state,
    remote: { ...state.remote, connection: "resync-required" },
    diagnostic,
  };
}

function retainKeys<T>(
  source: Readonly<Record<string, T>>,
  keys: readonly string[],
  fallback: T,
): Readonly<Record<string, T>> {
  return Object.fromEntries(keys.map((key) => [key, source[key] ?? fallback]));
}
