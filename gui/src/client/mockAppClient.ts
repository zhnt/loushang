import type {
  ClientEvent,
  ClientSnapshot,
  ControlReceipt,
  FixturePlaybackPort,
  PlaybackStep,
  RunProjection,
  SessionSnapshot,
  SubmitReceipt,
  SubmitTextInput,
} from "./model";

interface ScriptedStep {
  readonly sessionId: string;
  readonly label: string;
  readonly create: (cursor: string) => ClientEvent;
}

const activeRun: RunProjection = {
  id: "run-gui-b1",
  title: "Build the Workspace / Task / Review fixture",
  status: "running",
  currentTaskId: "task-inspect",
  tasks: [
    {
      id: "task-inspect",
      title: "Inspect GUI workspace and accepted specifications",
      status: "running",
      activityIds: ["activity-plan", "activity-read", "activity-command"],
      assignedAgentRunIds: ["agent-root"],
    },
    {
      id: "task-model",
      title: "Project Workspace, Run, Task and Activity fixtures",
      status: "pending",
      activityIds: [],
      assignedAgentRunIds: ["agent-root"],
    },
    {
      id: "task-review",
      title: "Review the fixture interaction boundary",
      status: "pending",
      activityIds: [],
      assignedAgentRunIds: ["agent-reviewer"],
    },
    {
      id: "task-verify",
      title: "Run deterministic UI checks",
      status: "pending",
      activityIds: [],
      assignedAgentRunIds: ["agent-root"],
    },
  ],
  activities: [
    {
      id: "activity-plan",
      taskId: "task-inspect",
      kind: "plan",
      label: "Planning the B1 fixture vertical slice",
      detail: "4 tasks · one derived AgentRun · read-only review",
      status: "completed",
      durationLabel: "1s",
    },
    {
      id: "activity-read",
      taskId: "task-inspect",
      kind: "read",
      label: "Read gui-interface-specification.md",
      detail: "Accepted layout and interaction evidence",
      status: "completed",
      durationLabel: "1s",
    },
    {
      id: "activity-command",
      taskId: "task-inspect",
      kind: "command",
      label: "Ran rg over GUI models and tests",
      detail: "rg -n \"SessionSnapshot|ChangeSet|Task\" gui/src gui/tests",
      status: "completed",
      durationLabel: "2s",
    },
  ],
  agentRuns: [
    {
      id: "agent-root",
      label: "Primary agent",
      role: "root",
      status: "running",
      taskIds: ["task-inspect", "task-model", "task-verify"],
      summary: "Owns the fixture implementation and verification.",
    },
    {
      id: "agent-reviewer",
      label: "Interface reviewer",
      role: "subagent",
      status: "pending",
      taskIds: ["task-review"],
      parentAgentRunId: "agent-root",
      summary: "Checks the interface boundary without editing runtime code.",
    },
  ],
};

const interfaceDiff = {
  id: "document-interface-diff",
  title: "gui-interface-specification.md",
  kind: "diff" as const,
  sourceLabel: "fixture://changes/codex/gui-interface-spec",
  revision: "fixture-f8a8f31c",
  content:
    "@@ -211,6 +211,11 @@ Transcript and Run activity timeline\n" +
    " SessionViewport shows messages and execution results.\n" +
    "+Activity groups retain their Run and Task identity.\n" +
    "+Collapsed groups show status, elapsed time and failures.\n" +
    "+Expanded groups show reads, commands and tool calls.\n" +
    "-The UI may infer plan steps from assistant text.\n" +
    "+The UI only renders accepted Task projections.",
};

const requirementsDiff = {
  id: "document-requirements-diff",
  title: "gui-requirements.md",
  kind: "diff" as const,
  sourceLabel: "fixture://changes/codex/gui-interface-spec",
  revision: "fixture-f8a8f31c",
  content:
    "@@ -120,3 +120,7 @@ User observable requirements\n" +
    "+GUI-FR-017 provides named read-only change review.\n" +
    "+GUI-FR-020 distinguishes Run, Task, Activity and AgentRun.\n" +
    "+Missing capabilities stay explicitly unavailable.",
};

const boundaryDiff = {
  id: "document-boundary-diff",
  title: "gui-system-context-and-boundary-contract.md",
  kind: "diff" as const,
  sourceLabel: "fixture://changes/codex/gui-interface-spec",
  revision: "fixture-f8a8f31c",
  content:
    "@@ -14,4 +14,5 @@ Target architecture\n" +
    " AppHost owns the accepted application lifecycle.\n" +
    "+HarnessGUI and Hosted Mux consume the same AppService facts.\n" +
    "-Desktop GUI owns repository discovery.\n" +
    "+Workspace facts arrive through a versioned client facet.",
};

const fixtureSnapshot: ClientSnapshot = {
  generation: "9007199254740993",
  connection: "fixture-offline",
  fixtureLabel: "Offline fixture · no AppService, repository access or model",
  capabilities: [
    { name: "workspace", version: "fixture/v2", availability: "fixture" },
    { name: "changes", version: "fixture/v2", availability: "fixture" },
    { name: "tasks", version: "fixture/v1", availability: "fixture" },
    { name: "agents", version: "fixture/v1", availability: "fixture" },
    { name: "artifacts", version: null, availability: "unavailable" },
  ],
  workspaces: [
    {
      id: "workspace-loushang",
      title: "Loushang",
      rootLabel: "C:\\fixture\\loushang",
      vcs: { kind: "git", label: "main", revision: "fixture-f8a8f31c" },
    },
    {
      id: "workspace-research",
      title: "Reference research",
      rootLabel: "C:\\fixture\\research",
      vcs: { kind: "svn", label: "trunk", revision: "fixture-r184" },
    },
    {
      id: "workspace-scratch",
      title: "Scratch",
      rootLabel: "C:\\fixture\\scratch",
      vcs: null,
    },
  ],
  selectedSessionId: "session-gui",
  recentSessionIds: ["session-gui", "session-ontology", "session-notes"],
  sessions: [
    {
      id: "session-gui",
      workspaceId: "workspace-loushang",
      title: "GUI development",
      status: "running",
      cursor: "9007199254741000",
      context: context("Loushang", "C:\\fixture\\loushang", "session-gui", "mux-gui"),
      messages: [
        {
          id: "message-gui-user-1",
          role: "user",
          content: "Continue the Workspace / Task / Review interface slice.",
          phase: "sent",
        },
        {
          id: "message-gui-assistant-1",
          role: "assistant",
          content:
            "The offline fixture now keeps Session, Run, Task, Activity and AgentRun as separate facts. The next activity is ready to play.",
          phase: "streaming",
        },
      ],
      documents: [
        {
          id: "document-boundary-note",
          title: "Boundary note.md",
          kind: "markdown",
          sourceLabel: "fixture://architecture/boundary-note",
          revision: "fixture-r1",
          content:
            "# HarnessGUI boundary\n\n- React owns presentation and local state.\n- Rust adapts the desktop and AppClient edge.\n- AppService remains the client-semantics authority.",
        },
        interfaceDiff,
        requirementsDiff,
        boundaryDiff,
      ],
      run: activeRun,
      changeSet: {
        id: "changeset-interface-spec",
        title: "Interface specification fixture",
        scopeLabel: "Previous turn · proposed branch",
        revision: "fixture-f8a8f31c",
        additions: 732,
        deletions: 106,
        files: [
          {
            id: "change-interface",
            path: "docs/internals/architecture/drafts/gui-interface-specification.md",
            status: "added",
            additions: 410,
            deletions: 2,
            documentId: interfaceDiff.id,
          },
          {
            id: "change-requirements",
            path: "docs/internals/architecture/drafts/gui-requirements.md",
            status: "modified",
            additions: 46,
            deletions: 32,
            documentId: requirementsDiff.id,
          },
          {
            id: "change-boundary",
            path: "docs/internals/architecture/drafts/gui-system-context-and-boundary-contract.md",
            status: "modified",
            additions: 35,
            deletions: 19,
            documentId: boundaryDiff.id,
          },
        ],
      },
    },
    session("session-provider", "workspace-loushang", "Provider review", "waiting", "100", "Loushang"),
    session("session-ontology", "workspace-research", "Operational ontology", "idle", "200", "Research"),
    session("session-codex", "workspace-research", "Reference system notes", "idle", "300", "Research"),
    session("session-notes", "workspace-scratch", "Architecture notes", "idle", "400", "Scratch"),
    session("session-playground", "workspace-scratch", "Fixture playground", "failed", "500", "Scratch"),
  ],
};

function context(project: string, rootLabel: string, sessionId: string, muxId: string) {
  return {
    project,
    rootLabel,
    applicationId: "app-fixture-01",
    muxId,
    memberId: `member-${sessionId}`,
    sessionId,
    source: "fixture" as const,
  };
}

function session(
  id: string,
  workspaceId: string,
  title: string,
  status: SessionSnapshot["status"],
  cursor: string,
  project: string,
): SessionSnapshot {
  return {
    id,
    workspaceId,
    title,
    status,
    cursor,
    context: context(project, `C:\\fixture\\${workspaceId}`, id, `mux-${id}`),
    messages: [
      {
        id: `${id}-message`,
        role: "assistant",
        content: status === "waiting" ? "This fixture Session needs input." : `Fixture transcript for ${title}.`,
        phase: "complete",
      },
    ],
    documents: [],
    run: null,
    changeSet: null,
  };
}

export class MockAppClient implements FixturePlaybackPort {
  private readonly listeners = new Set<(event: ClientEvent) => void>();
  private readonly cursors = new Map<string, bigint>();
  private readonly activeMessages = new Map<string, string>();
  private queue: ScriptedStep[];

  constructor() {
    for (const item of fixtureSnapshot.sessions) this.cursors.set(item.id, BigInt(item.cursor));
    this.activeMessages.set("session-gui", "message-gui-assistant-1");
    this.queue = this.activeRunScript();
  }

  async snapshot(): Promise<ClientSnapshot> {
    return structuredClone(fixtureSnapshot);
  }

  subscribe(listener: (event: ClientEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async submitText(input: SubmitTextInput): Promise<SubmitReceipt> {
    const text = input.text.trim();
    if (!text || !this.cursors.has(input.sessionId) || this.activeMessages.has(input.sessionId)) {
      return { submissionId: input.submissionId, accepted: false };
    }

    const assistantId = `${input.submissionId}:assistant`;
    this.activeMessages.set(input.sessionId, assistantId);
    this.queue = [
      ...this.queue.filter((step) => step.sessionId !== input.sessionId),
      ...this.responseScript(input.sessionId, assistantId),
    ];
    this.emit({
      type: "execution.accepted",
      id: `${input.submissionId}:accepted`,
      generation: fixtureSnapshot.generation,
      sessionId: input.sessionId,
      cursor: this.nextCursor(input.sessionId),
      submissionId: input.submissionId,
      userMessage: {
        id: `${input.submissionId}:user`,
        role: "user",
        content: text,
        phase: "sent",
      },
      assistantMessage: {
        id: assistantId,
        role: "assistant",
        content: "",
        phase: "streaming",
      },
      run: oneTaskRun(input.submissionId),
    });
    return { submissionId: input.submissionId, accepted: true };
  }

  async interrupt(sessionId: string): Promise<ControlReceipt> {
    const messageId = this.activeMessages.get(sessionId);
    if (!messageId) return { accepted: false, reason: "No fixture execution is running." };
    this.queue = this.queue.filter((step) => step.sessionId !== sessionId);
    this.activeMessages.delete(sessionId);
    this.emit({
      type: "execution.interrupted",
      id: `${messageId}:interrupted`,
      generation: fixtureSnapshot.generation,
      sessionId,
      cursor: this.nextCursor(sessionId),
      messageId,
      reason: "Interrupted by fixture user",
    });
    return { accepted: true };
  }

  async advanceFixture(): Promise<PlaybackStep | null> {
    const step = this.queue.shift();
    if (!step) return null;
    const event = step.create(this.nextCursor(step.sessionId));
    this.emit(event);
    if (event.type === "execution.completed") this.activeMessages.delete(step.sessionId);
    return { label: step.label, remaining: this.queue.length };
  }

  remainingFixtureSteps(): number {
    return this.queue.length;
  }

  private activeRunScript(): ScriptedStep[] {
    const sessionId = "session-gui";
    const envelope = (cursor: string) => ({
      generation: fixtureSnapshot.generation,
      sessionId,
      cursor,
    });
    return [
      {
        sessionId,
        label: "append a tool activity to task 1",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.activity.appended",
          id: "run-gui-b1:activity-tool",
          runId: activeRun.id,
          activity: {
            id: "activity-tool",
            taskId: "task-inspect",
            kind: "tool",
            label: "Inspected the accepted GUI requirements",
            detail: "Fixture tool call · no repository access",
            status: "completed",
            durationLabel: "1s",
          },
        }),
      },
      {
        sessionId,
        label: "complete task 1 and start task 2",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.tasks.updated",
          id: "run-gui-b1:task-transition-1-2",
          runId: activeRun.id,
          updates: [
            { taskId: "task-inspect", status: "completed" },
            { taskId: "task-model", status: "running" },
          ],
          currentTaskId: "task-model",
        }),
      },
      {
        sessionId,
        label: "append the model projection activity",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.activity.appended",
          id: "run-gui-b1:activity-model",
          runId: activeRun.id,
          activity: {
            id: "activity-model",
            taskId: "task-model",
            kind: "command",
            label: "Projected Workspace, Run and ChangeSet fixture values",
            detail: "TypeScript fixture reducer · no AppService connection",
            status: "completed",
            durationLabel: "3s",
          },
        }),
      },
      {
        sessionId,
        label: "complete task 2 and start task 3",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.tasks.updated",
          id: "run-gui-b1:task-transition-2-3",
          runId: activeRun.id,
          updates: [
            { taskId: "task-model", status: "completed" },
            { taskId: "task-review", status: "running" },
          ],
          currentTaskId: "task-review",
        }),
      },
      {
        sessionId,
        label: "start the derived reviewer AgentRun",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.agent.updated",
          id: "run-gui-b1:reviewer-running",
          runId: activeRun.id,
          agentRunId: "agent-reviewer",
          status: "running",
        }),
      },
      {
        sessionId,
        label: "append the reviewer result",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.activity.appended",
          id: "run-gui-b1:activity-review",
          runId: activeRun.id,
          activity: {
            id: "activity-review",
            taskId: "task-review",
            kind: "result",
            label: "Reviewed the interface boundary",
            detail: "Task and AgentRun identities remain distinct",
            status: "completed",
            durationLabel: "2s",
          },
        }),
      },
      {
        sessionId,
        label: "complete the derived reviewer AgentRun",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.agent.updated",
          id: "run-gui-b1:reviewer-completed",
          runId: activeRun.id,
          agentRunId: "agent-reviewer",
          status: "completed",
          summary: "Confirmed the Product-neutral UI boundary and read-only review path.",
        }),
      },
      {
        sessionId,
        label: "complete task 3 and start task 4",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.tasks.updated",
          id: "run-gui-b1:task-transition-3-4",
          runId: activeRun.id,
          updates: [
            { taskId: "task-review", status: "completed" },
            { taskId: "task-verify", status: "running" },
          ],
          currentTaskId: "task-verify",
        }),
      },
      {
        sessionId,
        label: "append the verification activity",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.activity.appended",
          id: "run-gui-b1:activity-verify",
          runId: activeRun.id,
          activity: {
            id: "activity-verify",
            taskId: "task-verify",
            kind: "command",
            label: "Ran the deterministic GUI check",
            detail: "pnpm run check",
            status: "completed",
            durationLabel: "6s",
          },
        }),
      },
      {
        sessionId,
        label: "complete task 4",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "run.tasks.updated",
          id: "run-gui-b1:task-4-completed",
          runId: activeRun.id,
          updates: [{ taskId: "task-verify", status: "completed" }],
          currentTaskId: null,
        }),
      },
      {
        sessionId,
        label: "complete the fixture Run",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "execution.completed",
          id: "run-gui-b1:completed",
          messageId: "message-gui-assistant-1",
        }),
      },
    ];
  }

  private responseScript(sessionId: string, messageId: string): ScriptedStep[] {
    const envelope = (cursor: string) => ({
      generation: fixtureSnapshot.generation,
      sessionId,
      cursor,
    });
    return [
      {
        sessionId,
        label: "stream first response chunk",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "output.delta",
          id: `${messageId}:delta-1`,
          messageId,
          delta: "The GUI keeps a separate client scope ",
        }),
      },
      {
        sessionId,
        label: "stream second response chunk",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "output.delta",
          id: `${messageId}:delta-2`,
          messageId,
          delta: "and projects shared service facts through its UI port.",
        }),
      },
      {
        sessionId,
        label: "complete fixture execution",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "execution.completed",
          id: `${messageId}:completed`,
          messageId,
        }),
      },
    ];
  }

  private nextCursor(sessionId: string): string {
    const next = (this.cursors.get(sessionId) ?? 0n) + 1n;
    this.cursors.set(sessionId, next);
    return next.toString();
  }

  private emit(event: ClientEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}

function oneTaskRun(id: string): RunProjection {
  return {
    id: `${id}:run`,
    title: "Fixture response",
    status: "running",
    currentTaskId: `${id}:task`,
    tasks: [
      {
        id: `${id}:task`,
        title: "Produce fixture response",
        status: "running",
        activityIds: [],
        assignedAgentRunIds: [`${id}:agent`],
      },
    ],
    activities: [],
    agentRuns: [
      {
        id: `${id}:agent`,
        label: "Primary agent",
        role: "root",
        status: "running",
        taskIds: [`${id}:task`],
      },
    ],
  };
}

export function createMockAppClient(): MockAppClient {
  return new MockAppClient();
}
