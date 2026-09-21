import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { ExecutionSessionSnapshotV1, MuxSpaceV1, SessionIdentityV1 } from "../../contracts/generated/bridge";
import type {
  ClientEvent,
  ClientSnapshot,
  ConversationMessage,
  HarnessClientUiPort,
  SessionSnapshot,
} from "./model";

interface NativeInitialSnapshot {
  readonly serviceInstanceId: string;
  readonly muxSpace: MuxSpaceV1;
  readonly sessions: readonly ExecutionSessionSnapshotV1[];
}

export async function nativeLiveAvailable(): Promise<boolean> {
  return isTauri() && await invoke<boolean>("live_readonly_available");
}

export function createNativeLiveClient(): HarnessClientUiPort {
  let initial: Promise<ClientSnapshot> | null = null;
  return {
    snapshot() {
      initial ??= receiveInitialSnapshot().then(projectSnapshot);
      return initial;
    },
    subscribe(_listener: (event: ClientEvent) => void) {
      // The first slice publishes one atomic snapshot. Live deltas follow in a
      // separate acceptance slice and must not be inferred from UI history.
      return () => undefined;
    },
    async submitText(input) {
      return { submissionId: input.submissionId, accepted: false };
    },
    async interrupt() {
      return { accepted: false, reason: "The live connection is read-only." };
    },
  };
}

async function receiveInitialSnapshot(): Promise<NativeInitialSnapshot> {
  let resolveSnapshot!: (snapshot: NativeInitialSnapshot) => void;
  let rejectSnapshot!: (error: Error) => void;
  const received = new Promise<NativeInitialSnapshot>((resolve, reject) => {
    resolveSnapshot = resolve;
    rejectSnapshot = reject;
  });
  const unlistenSnapshot = await listen<unknown>("gui://live-initial-snapshot", (event) => {
    try {
      resolveSnapshot(validateInitialSnapshot(event.payload));
    } catch {
      rejectSnapshot(new Error("The native initial snapshot was invalid."));
    }
  });
  const unlistenFailure = await listen("gui://live-connection-failed", () => {
    rejectSnapshot(new Error("The native live connection failed."));
  });
  const timer = window.setTimeout(
    () => rejectSnapshot(new Error("The native initial snapshot timed out.")),
    7_000,
  );
  try {
    await invoke("start_live_readonly");
    return await received;
  } catch (error) {
    await invoke("stop_live_readonly").catch(() => undefined);
    throw error;
  } finally {
    window.clearTimeout(timer);
    unlistenSnapshot();
    unlistenFailure();
  }
}

function validateInitialSnapshot(value: unknown): NativeInitialSnapshot {
  const root = object(value);
  const serviceInstanceId = identifier(root.serviceInstanceId);
  const mux = object(root.muxSpace);
  const muxSpaceId = identifier(mux.muxSpaceId);
  const name = text(mux.name, 256);
  const revision = decimal(mux.revision);
  if (!Array.isArray(mux.members) || !Array.isArray(root.sessions)) throw new Error("arrays");
  if (mux.members.length !== root.sessions.length || mux.members.length > 128) throw new Error("membership");
  const members = mux.members.map((raw, index) => {
    const member = object(raw);
    const session = identity(member.session);
    if (decimal(member.position) !== String(index + 1)) throw new Error("position");
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
    return raw as ExecutionSessionSnapshotV1;
  });
  return {
    serviceInstanceId,
    muxSpace: { muxSpaceId, name, revision, members },
    sessions,
  };
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
    },
    capabilities: [
      "workspace", "changes", "artifacts", "tasks", "agents",
    ].map((name) => ({
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
    : terminal === "failed"
      ? "failed"
      : terminal === "interrupted"
        ? "interrupted"
        : "idle";
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
