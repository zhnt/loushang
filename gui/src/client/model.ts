export type ConnectionState =
  | "fixture-offline"
  | "connected"
  | "disconnected"
  | "resync-required";

export type SessionStatus =
  | "idle"
  | "running"
  | "waiting"
  | "interrupted"
  | "failed";

export type MessagePhase =
  | "sent"
  | "streaming"
  | "complete"
  | "interrupted"
  | "failed";

export type RunStatus = "running" | "waiting" | "completed" | "failed" | "interrupted";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type ActivityStatus = "running" | "completed" | "failed" | "waiting";
export type AgentRunStatus = "pending" | "running" | "completed" | "failed" | "interrupted";

export interface VersionControlSummary {
  readonly kind: "git" | "svn";
  readonly label: string;
  readonly revision: string;
}

export interface WorkspaceSummary {
  readonly id: string;
  readonly title: string;
  readonly rootLabel: string;
  readonly vcs: VersionControlSummary | null;
}

export interface ContextIdentity {
  readonly project: string;
  readonly rootLabel: string;
  readonly applicationId: string;
  readonly muxId: string;
  readonly memberId: string;
  readonly sessionId: string;
  readonly source: "fixture";
}

export interface ConversationMessage {
  readonly id: string;
  readonly role: "user" | "assistant";
  readonly content: string;
  readonly phase: MessagePhase;
}

export interface ActivityProjection {
  readonly id: string;
  readonly taskId: string;
  readonly kind: "plan" | "read" | "command" | "tool" | "wait" | "result";
  readonly label: string;
  readonly detail?: string;
  readonly status: ActivityStatus;
  readonly durationLabel?: string;
}

export interface TaskProjection {
  readonly id: string;
  readonly title: string;
  readonly status: TaskStatus;
  readonly activityIds: readonly string[];
  readonly assignedAgentRunIds: readonly string[];
}

export interface AgentRunProjection {
  readonly id: string;
  readonly label: string;
  readonly role: "root" | "subagent";
  readonly status: AgentRunStatus;
  readonly taskIds: readonly string[];
  readonly parentAgentRunId?: string;
  readonly summary?: string;
}

export interface RunProjection {
  readonly id: string;
  readonly title: string;
  readonly status: RunStatus;
  readonly currentTaskId: string | null;
  readonly tasks: readonly TaskProjection[];
  readonly activities: readonly ActivityProjection[];
  readonly agentRuns: readonly AgentRunProjection[];
}

export type DocumentKind = "markdown" | "text" | "diff";

export interface ReadonlyDocument {
  readonly id: string;
  readonly title: string;
  readonly kind: DocumentKind;
  readonly sourceLabel: string;
  readonly revision: string;
  readonly content: string;
}

export interface FileChangeProjection {
  readonly id: string;
  readonly path: string;
  readonly status: "added" | "modified" | "deleted" | "renamed";
  readonly additions: number;
  readonly deletions: number;
  readonly documentId: string;
}

export interface ChangeSetProjection {
  readonly id: string;
  readonly title: string;
  readonly scopeLabel: string;
  readonly revision: string;
  readonly additions: number;
  readonly deletions: number;
  readonly files: readonly FileChangeProjection[];
}

export interface SessionSnapshot {
  readonly id: string;
  readonly workspaceId: string;
  readonly title: string;
  readonly status: SessionStatus;
  readonly cursor: string;
  readonly context: ContextIdentity;
  readonly messages: readonly ConversationMessage[];
  readonly documents: readonly ReadonlyDocument[];
  readonly run: RunProjection | null;
  readonly changeSet: ChangeSetProjection | null;
}

export interface CapabilitySummary {
  readonly name: "workspace" | "changes" | "artifacts" | "tasks" | "agents";
  readonly version: string | null;
  readonly availability: "fixture" | "unavailable";
}

export interface ClientSnapshot {
  readonly generation: string;
  readonly connection: ConnectionState;
  readonly fixtureLabel: string;
  readonly capabilities: readonly CapabilitySummary[];
  readonly workspaces: readonly WorkspaceSummary[];
  readonly sessions: readonly SessionSnapshot[];
  readonly recentSessionIds: readonly string[];
  readonly selectedSessionId: string;
}

interface EventEnvelope {
  readonly id: string;
  readonly generation: string;
  readonly sessionId: string;
  readonly cursor: string;
}

export type ClientEvent =
  | (EventEnvelope & {
      readonly type: "execution.accepted";
      readonly submissionId: string;
      readonly userMessage: ConversationMessage;
      readonly assistantMessage: ConversationMessage;
      readonly run: RunProjection | null;
    })
  | (EventEnvelope & {
      readonly type: "output.delta";
      readonly messageId: string;
      readonly delta: string;
    })
  | (EventEnvelope & {
      readonly type: "document.available";
      readonly document: ReadonlyDocument;
    })
  | (EventEnvelope & {
      readonly type: "run.activity.appended";
      readonly runId: string;
      readonly activity: ActivityProjection;
    })
  | (EventEnvelope & {
      readonly type: "run.tasks.updated";
      readonly runId: string;
      readonly updates: readonly {
        readonly taskId: string;
        readonly status: TaskStatus;
      }[];
      readonly currentTaskId: string | null;
    })
  | (EventEnvelope & {
      readonly type: "run.agent.updated";
      readonly runId: string;
      readonly agentRunId: string;
      readonly status: AgentRunStatus;
      readonly summary?: string;
    })
  | (EventEnvelope & {
      readonly type: "execution.completed";
      readonly messageId: string;
    })
  | (EventEnvelope & {
      readonly type: "execution.interrupted";
      readonly messageId: string;
      readonly reason: string;
    });

export interface SubmitTextInput {
  readonly sessionId: string;
  readonly submissionId: string;
  readonly text: string;
}

export interface SubmitReceipt {
  readonly submissionId: string;
  readonly accepted: boolean;
}

export interface ControlReceipt {
  readonly accepted: boolean;
  readonly reason?: string;
}

export interface PlaybackStep {
  readonly label: string;
  readonly remaining: number;
}

export interface HarnessClientUiPort {
  snapshot(): Promise<ClientSnapshot>;
  subscribe(listener: (event: ClientEvent) => void): () => void;
  submitText(input: SubmitTextInput): Promise<SubmitReceipt>;
  interrupt(sessionId: string): Promise<ControlReceipt>;
}

export interface FixturePlaybackPort extends HarnessClientUiPort {
  advanceFixture(): Promise<PlaybackStep | null>;
  remainingFixtureSteps(): number;
}
