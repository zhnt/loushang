import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { ExecutionSessionSnapshotV1, MuxSpaceV1, SessionIdentityV1 } from "../../contracts/generated/bridge";
import type {
  ClientEvent,
  ClientSnapshot,
  ConversationMessage,
  HarnessClientUiPort,
  SessionSnapshot,
} from "./model";

interface NativeInitialSnapshot {
  readonly connectionEpoch: string;
  readonly serviceInstanceId: string;
  readonly muxSpace: MuxSpaceV1;
  readonly sessions: readonly ExecutionSessionSnapshotV1[];
}

interface NativeMemberEvents {
  readonly memberId: string;
  readonly sessionId: string;
  readonly events: readonly unknown[];
}

interface NativeConnectionState {
  readonly state: "connecting" | "disconnected";
  readonly connectionEpoch: string;
}

const EVENT_KINDS = new Set([
  "turn_started", "user_message", "assistant_delta", "assistant_message", "status", "error",
  "turn_completed", "turn_interrupted", "interaction_requested", "interaction_dismissed",
]);

export async function nativeLiveAvailable(): Promise<boolean> {
  return isTauri() && await invoke<boolean>("live_readonly_available");
}

export function createNativeLiveClient(): HarnessClientUiPort {
  let current: NativeInitialSnapshot | null = null;
  let sequence = "0";
  let contentCursors = new Map<string, string>();
  let executionRevisions = new Map<string, number>();
  let started: Promise<void> | null = null;
  let deliveredInitial = false;
  let resolveInitial!: (snapshot: NativeInitialSnapshot) => void;
  let rejectInitial!: (error: Error) => void;
  const initial = new Promise<NativeInitialSnapshot>((resolve, reject) => {
    resolveInitial = resolve;
    rejectInitial = reject;
  });
  const snapshotListeners = new Set<(snapshot: ClientSnapshot) => void>();
  const connectionListeners = new Set<(state: "disconnected" | "resync-required") => void>();

  const notifyConnection = (state: "disconnected" | "resync-required") => {
    for (const listener of connectionListeners) listener(state);
  };

  const acceptInitial = (value: unknown) => {
    const next = validateInitialSnapshot(value);
    current = next;
    sequence = "0";
    contentCursors = new Map(next.sessions.map((session) => [
      session.source.source.identity.sessionId,
      session.source.source.cursor,
    ]));
    executionRevisions = new Map(next.sessions.map((session) => [
      session.source.source.identity.sessionId,
      session.executions.revision,
    ]));
    if (deliveredInitial) {
      const projected = projectSnapshot(next);
      for (const listener of snapshotListeners) listener(projected);
    } else {
      resolveInitial(next);
    }
  };

  const acceptRound = (value: unknown) => {
    if (!current) {
      notifyConnection("resync-required");
      return;
    }
    try {
      const next = validateEventRound(
        value,
        current,
        sequence,
        contentCursors,
        executionRevisions,
      );
      current = next.snapshot;
      sequence = next.sequence;
      contentCursors = next.contentCursors;
      executionRevisions = next.executionRevisions;
      const projected = projectSnapshot(next.snapshot);
      for (const listener of snapshotListeners) listener(projected);
    } catch {
      notifyConnection("resync-required");
    }
  };

  async function start(): Promise<void> {
    const unlisteners: UnlistenFn[] = [];
    try {
      unlisteners.push(await listen<unknown>("gui://live-initial-snapshot", (event) => {
        try {
          acceptInitial(event.payload);
        } catch {
          notifyConnection("resync-required");
        }
      }));
      unlisteners.push(await listen<unknown>("gui://live-event-round", (event) => {
        acceptRound(event.payload);
      }));
      unlisteners.push(await listen<unknown>("gui://live-connection-state", (event) => {
        try {
          const state = validateConnectionState(event.payload);
          if (state.state === "disconnected"
            && (!current || state.connectionEpoch === current.connectionEpoch)) {
            notifyConnection("disconnected");
          }
        } catch {
          notifyConnection("resync-required");
        }
      }));
      unlisteners.push(await listen("gui://live-connection-failed", () => {
        rejectInitial(new Error("The native live connection failed."));
        notifyConnection("resync-required");
      }));
      await invoke("start_live_readonly");
    } catch (error) {
      for (const unlisten of unlisteners) unlisten();
      rejectInitial(error instanceof Error ? error : new Error("Unable to start native live connection."));
      throw error;
    }
  }

  const ensureStarted = () => {
    started ??= start();
    return started;
  };

  return {
    async snapshot() {
      await ensureStarted();
      if (current) {
        deliveredInitial = true;
        return projectSnapshot(current);
      }
      let timer = 0;
      const timeout = new Promise<never>((_resolve, reject) => {
        timer = window.setTimeout(
          () => reject(new Error("The native initial snapshot timed out.")),
          15_000,
        );
      });
      try {
        const snapshot = await Promise.race([initial, timeout]);
        deliveredInitial = true;
        // A round or reconnect can arrive between resolving the first snapshot
        // and this continuation. Never overwrite that newer accepted state.
        return projectSnapshot(current ?? snapshot);
      } finally {
        window.clearTimeout(timer);
      }
    },
    subscribe(_listener: (event: ClientEvent) => void) {
      return () => undefined;
    },
    subscribeSnapshots(listener) {
      snapshotListeners.add(listener);
      return () => snapshotListeners.delete(listener);
    },
    subscribeConnection(listener) {
      connectionListeners.add(listener);
      return () => connectionListeners.delete(listener);
    },
    async requestResync() {
      await ensureStarted();
      await invoke("resync_live_readonly");
    },
    async submitText(input) {
      return { submissionId: input.submissionId, accepted: false };
    },
    async interrupt() {
      return { accepted: false, reason: "The live connection is read-only." };
    },
  };
}

function validateInitialSnapshot(value: unknown): NativeInitialSnapshot {
  const root = object(value);
  const connectionEpoch = positiveDecimal(root.connectionEpoch);
  const serviceInstanceId = identifier(root.serviceInstanceId);
  const mux = object(root.muxSpace);
  const muxSpaceId = identifier(mux.muxSpaceId);
  const name = text(mux.name, 256);
  const revision = positiveDecimal(mux.revision);
  if (!Array.isArray(mux.members) || !Array.isArray(root.sessions)) throw new Error("arrays");
  if (mux.members.length !== root.sessions.length || mux.members.length > 128) throw new Error("membership");
  const members = mux.members.map((raw, index) => {
    const member = object(raw);
    const session = identity(member.session);
    if (positiveDecimal(member.position) !== String(index + 1)) throw new Error("position");
    return {
      memberId: identifier(member.memberId),
      session,
      title: text(member.title, 256),
      position: String(index + 1),
    };
  });
  const sessions = root.sessions.map((raw, index) => {
    const session = object(raw);
    if (identifier(session.serviceInstanceId) !== serviceInstanceId) throw new Error("instance");
    const source = object(session.source);
    const sourceSnapshot = object(source.source);
    const sourceIdentity = identity(sourceSnapshot.identity);
    if (sourceIdentity.sessionId !== members[index].session.sessionId) throw new Error("identity");
    decimal(sourceSnapshot.cursor);
    decimal(sourceSnapshot.revision);
    if (typeof sourceSnapshot.running !== "boolean" || !Array.isArray(sourceSnapshot.records)) throw new Error("source");
    const executions = object(session.executions);
    safeCounter(executions.revision);
    return raw as ExecutionSessionSnapshotV1;
  });
  return {
    connectionEpoch,
    serviceInstanceId,
    muxSpace: { muxSpaceId, name, revision, members },
    sessions,
  };
}

function validateEventRound(
  value: unknown,
  current: NativeInitialSnapshot,
  previousSequence: string,
  priorContentCursors: ReadonlyMap<string, string>,
  priorExecutionRevisions: ReadonlyMap<string, number>,
): {
  readonly snapshot: NativeInitialSnapshot;
  readonly sequence: string;
  readonly contentCursors: Map<string, string>;
  readonly executionRevisions: Map<string, number>;
} {
  const root = object(value);
  if (positiveDecimal(root.connectionEpoch) !== current.connectionEpoch
    || identifier(root.serviceInstanceId) !== current.serviceInstanceId
    || identifier(root.muxSpaceId) !== current.muxSpace.muxSpaceId) throw new Error("round identity");
  const sequence = positiveDecimal(root.sequence);
  if (sequence !== successor(previousSequence)) throw new Error("round sequence");
  if (!Array.isArray(root.members) || root.members.length !== current.muxSpace.members.length
    || !Array.isArray(root.sessions)) throw new Error("round arrays");
  const contentCursors = new Map(priorContentCursors);
  const executionRevisions = new Map(priorExecutionRevisions);
  const members = root.members.map((raw, index): NativeMemberEvents => {
    const item = object(raw);
    const expected = current.muxSpace.members[index];
    const memberId = identifier(item.memberId);
    const sessionId = identifier(item.sessionId);
    if (memberId !== expected.memberId || sessionId !== expected.session.sessionId
      || !Array.isArray(item.events)) throw new Error("round member");
    for (const rawEvent of item.events) {
      const event = object(rawEvent);
      if ("source" in event) {
        const source = object(event.source);
        if (identifier(source.sessionId) !== sessionId || !EVENT_KINDS.has(String(source.kind))) {
          throw new Error("content event");
        }
        const cursor = positiveDecimal(source.cursor);
        if (cursor !== successor(contentCursors.get(sessionId) ?? "0")) throw new Error("content cursor");
        contentCursors.set(sessionId, cursor);
      } else {
        const revision = safeCounter(event.revision);
        if (revision !== (executionRevisions.get(sessionId) ?? 0) + 1) throw new Error("execution revision");
        object(event.execution);
        executionRevisions.set(sessionId, revision);
      }
    }
    return { memberId, sessionId, events: item.events };
  });
  const snapshot = validateInitialSnapshot({
    connectionEpoch: current.connectionEpoch,
    serviceInstanceId: current.serviceInstanceId,
    muxSpace: current.muxSpace,
    sessions: root.sessions,
  });
  snapshot.sessions.forEach((session, index) => {
    const sessionId = members[index].sessionId;
    const cursor = session.source.source.cursor;
    const before = current.sessions[index].source.source.cursor;
    if (compareDecimal(cursor, before) < 0
      || compareDecimal(cursor, contentCursors.get(sessionId) ?? "0") < 0
      || session.executions.revision < (executionRevisions.get(sessionId) ?? 0)) {
      throw new Error("snapshot watermark");
    }
  });
  return { snapshot, sequence, contentCursors, executionRevisions };
}

function validateConnectionState(value: unknown): NativeConnectionState {
  const root = object(value);
  const state = root.state;
  if (state !== "connecting" && state !== "disconnected") throw new Error("connection state");
  return { state, connectionEpoch: positiveDecimal(root.connectionEpoch) };
}

function projectSnapshot(initial: NativeInitialSnapshot): ClientSnapshot {
  const sessions = initial.sessions.map((snapshot, index) =>
    projectSession(initial, snapshot, initial.muxSpace.members[index].memberId, index),
  );
  return {
    generation: initial.muxSpace.revision,
    connection: "connected",
    source: {
      kind: "live",
      serviceInstanceId: initial.serviceInstanceId,
      muxSpaceId: initial.muxSpace.muxSpaceId,
      connectionEpoch: initial.connectionEpoch,
    },
    capabilities: ["workspace", "changes", "artifacts", "tasks", "agents"].map((name) => ({
      name: name as ClientSnapshot["capabilities"][number]["name"],
      version: null,
      availability: "unavailable" as const,
    })),
    workspaces: [],
    sessions,
    recentSessionIds: sessions.map((session) => session.id),
    selectedSessionId: sessions[0]?.id ?? "",
  };
}

export function projectNativeInitialSnapshot(value: unknown): ClientSnapshot {
  return projectSnapshot(validateInitialSnapshot(value));
}

export function projectNativeEventRound(initial: unknown, round: unknown): ClientSnapshot {
  const snapshot = validateInitialSnapshot(initial);
  const cursors = new Map(snapshot.sessions.map((session) => [
    session.source.source.identity.sessionId,
    session.source.source.cursor,
  ]));
  const revisions = new Map(snapshot.sessions.map((session) => [
    session.source.source.identity.sessionId,
    session.executions.revision,
  ]));
  return projectSnapshot(validateEventRound(round, snapshot, "0", cursors, revisions).snapshot);
}

function projectSession(
  initial: NativeInitialSnapshot,
  snapshot: ExecutionSessionSnapshotV1,
  memberId: string,
  memberIndex: number,
): SessionSnapshot {
  const source = snapshot.source.source;
  const messages: ConversationMessage[] = source.records.map((record, index) => ({
    id: `live-${source.identity.sessionId}-${index}`,
    role: record.kind === "user" ? "user" as const : "assistant" as const,
    content: record.text,
    phase: record.kind === "error" ? "failed" as const : "complete" as const,
  }));
  if (snapshot.source.draft) {
    messages.push({
      id: `live-${source.identity.sessionId}-draft`,
      role: "assistant",
      content: snapshot.source.draft,
      phase: "streaming",
    });
  }
  const terminal = snapshot.executions.latestTerminal?.status;
  const status = source.running || snapshot.executions.active
    ? "running"
    : terminal === "failed" ? "failed" : terminal === "interrupted" ? "interrupted" : "idle";
  return {
    id: source.identity.sessionId,
    workspaceId: `live-mux-${initial.muxSpace.muxSpaceId}`,
    title: source.title || initial.muxSpace.members[memberIndex].title,
    status,
    cursor: source.cursor,
    context: {
      project: source.identity.productId,
      rootLabel: `${source.identity.scope}:${source.identity.scopeFingerprint.slice(0, 12)}`,
      applicationId: initial.serviceInstanceId,
      muxId: initial.muxSpace.muxSpaceId,
      memberId,
      sessionId: source.identity.sessionId,
      source: "live",
    },
    messages,
    documents: [],
    run: null,
    changeSet: null,
  };
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("object");
  return value as Record<string, unknown>;
}
function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._~-]{0,511}$/.test(value)) throw new Error("identifier");
  return value;
}
function decimal(value: unknown): string {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]*)$/.test(value)) throw new Error("decimal");
  return value;
}
function positiveDecimal(value: unknown): string {
  const result = decimal(value);
  if (result === "0") throw new Error("positive decimal");
  return result;
}
function safeCounter(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("counter");
  return value;
}
function successor(value: string): string {
  const digits = [...decimal(value)];
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    if (digits[index] !== "9") {
      digits[index] = String(Number(digits[index]) + 1);
      return digits.join("");
    }
    digits[index] = "0";
  }
  return `1${digits.join("")}`;
}
function compareDecimal(left: string, right: string): number {
  const a = decimal(left); const b = decimal(right);
  if (a.length !== b.length) return a.length - b.length;
  return a < b ? -1 : a > b ? 1 : 0;
}
function text(value: unknown, maximum: number): string {
  if (typeof value !== "string" || !value.trim() || [...value].length > maximum) throw new Error("text");
  return value;
}
function identity(value: unknown): SessionIdentityV1 {
  const item = object(value);
  return {
    productId: identifier(item.productId),
    continuityId: identifier(item.continuityId),
    sessionId: identifier(item.sessionId),
    scope: item.scope === "cwd" || item.scope === "user_home" ? item.scope : (() => { throw new Error("scope"); })(),
    scopeFingerprint: typeof item.scopeFingerprint === "string" && /^[0-9a-f]{64}$/.test(item.scopeFingerprint)
      ? item.scopeFingerprint : (() => { throw new Error("fingerprint"); })(),
  };
}
