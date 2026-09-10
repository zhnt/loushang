import type {
  ClientEvent,
  ClientSnapshot,
  ConnectionState,
  ReadonlyDocument,
  SessionSnapshot,
} from "./model";

export interface RemoteState {
  readonly generation: string;
  readonly connection: ConnectionState;
  readonly fixtureLabel: string;
  readonly capabilities: ClientSnapshot["capabilities"];
  readonly sessions: Readonly<Record<string, SessionSnapshot>>;
  readonly sessionOrder: readonly string[];
}

export interface LocalState {
  readonly selectedSessionId: string | null;
  readonly drafts: Readonly<Record<string, string>>;
  readonly selectedDocuments: Readonly<Record<string, string | null>>;
  readonly unread: Readonly<Record<string, boolean>>;
}

export interface GuiState {
  readonly remote: RemoteState;
  readonly local: LocalState;
  readonly diagnostic: string | null;
}

export type GuiAction =
  | { readonly type: "snapshot.installed"; readonly snapshot: ClientSnapshot }
  | { readonly type: "session.selected"; readonly sessionId: string }
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
      fixtureLabel: "",
      capabilities: [],
      sessions: {},
      sessionOrder: [],
    },
    local: {
      selectedSessionId: null,
      drafts: {},
      selectedDocuments: {},
      unread: {},
    },
    diagnostic: null,
  };
}

export function guiReducer(state: GuiState, action: GuiAction): GuiState {
  switch (action.type) {
    case "snapshot.installed":
      return installSnapshot(state, action.snapshot);
    case "session.selected":
      if (!state.remote.sessions[action.sessionId]) return state;
      return {
        ...state,
        local: {
          ...state.local,
          selectedSessionId: action.sessionId,
          unread: { ...state.local.unread, [action.sessionId]: false },
        },
      };
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
  const sessions = Object.fromEntries(
    snapshot.sessions.map((session) => [session.id, session]),
  );
  const sessionIds = snapshot.sessions.map((session) => session.id);
  const drafts = retainKeys(state.local.drafts, sessionIds, "");
  const unread = retainKeys(state.local.unread, sessionIds, false);
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

  return {
    remote: {
      generation: snapshot.generation,
      connection: snapshot.connection,
      fixtureLabel: snapshot.fixtureLabel,
      capabilities: snapshot.capabilities,
      sessions,
      sessionOrder: sessionIds,
    },
    local: { selectedSessionId, drafts, selectedDocuments, unread },
    diagnostic: null,
  };
}

function applyEvent(state: GuiState, event: ClientEvent): GuiState {
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
      unread: isInactive
        ? { ...state.local.unread, [event.sessionId]: true }
        : state.local.unread,
    },
    diagnostic: null,
  };
}

function reduceSession(
  session: SessionSnapshot,
  event: ClientEvent,
): SessionSnapshot {
  switch (event.type) {
    case "execution.accepted":
      return {
        ...session,
        cursor: event.cursor,
        status: "running",
        messages: [
          ...session.messages,
          event.userMessage,
          event.assistantMessage,
        ],
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
    case "execution.completed":
      return {
        ...session,
        cursor: event.cursor,
        status: "idle",
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
  return documents.map((document, index) =>
    index === existing ? incoming : document,
  );
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
