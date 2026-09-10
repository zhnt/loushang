import type {
  ClientEvent,
  ClientSnapshot,
  ControlReceipt,
  FixturePlaybackPort,
  PlaybackStep,
  SubmitReceipt,
  SubmitTextInput,
} from "./model";

interface ScriptedStep {
  readonly sessionId: string;
  readonly label: string;
  readonly create: (cursor: string) => ClientEvent;
}

const fixtureSnapshot: ClientSnapshot = {
  generation: "9007199254740993",
  connection: "fixture-offline",
  fixtureLabel: "Offline fixture · no AppService or model",
  capabilities: [
    { name: "workspace", version: "fixture/v1", availability: "fixture" },
    { name: "changes", version: "fixture/v1", availability: "fixture" },
    { name: "artifacts", version: null, availability: "unavailable" },
  ],
  selectedSessionId: "session-gui",
  sessions: [
    {
      id: "session-gui",
      title: "GUI architecture",
      status: "idle",
      cursor: "9007199254741000",
      context: {
        project: "Loushang",
        rootLabel: "C:\\fixture\\loushang",
        applicationId: "app-fixture-01",
        muxId: "mux-gui",
        memberId: "member-gui",
        sessionId: "session-gui",
        source: "fixture",
      },
      messages: [
        {
          id: "message-gui-user-1",
          role: "user",
          content: "How should HarnessGUI share an AppHost with Hosted Mux?",
          phase: "sent",
        },
        {
          id: "message-gui-assistant-1",
          role: "assistant",
          content:
            "They may share one detachable application while keeping separate client scopes, generations, and UI-local state.",
          phase: "complete",
        },
      ],
      documents: [
        {
          id: "document-boundary",
          title: "Boundary note.md",
          kind: "markdown",
          sourceLabel: "fixture://architecture/boundary-note",
          revision: "fixture-r1",
          content:
            "# HarnessGUI boundary\n\n- React owns presentation and local state.\n- Rust adapts the desktop and AppClient edge.\n- AppService remains the client-semantics authority.",
        },
      ],
    },
    {
      id: "session-review",
      title: "Provider review",
      status: "waiting",
      cursor: "42",
      context: {
        project: "Loushang",
        rootLabel: "C:\\fixture\\loushang",
        applicationId: "app-fixture-01",
        muxId: "mux-review",
        memberId: "member-review",
        sessionId: "session-review",
        source: "fixture",
      },
      messages: [
        {
          id: "message-review-assistant-1",
          role: "assistant",
          content: "Review is paused at a fixture-only approval boundary.",
          phase: "complete",
        },
      ],
      documents: [],
    },
  ],
};

export class MockAppClient implements FixturePlaybackPort {
  private readonly listeners = new Set<(event: ClientEvent) => void>();
  private readonly cursors = new Map<string, bigint>();
  private readonly activeMessages = new Map<string, string>();
  private queue: ScriptedStep[] = [];

  constructor() {
    for (const session of fixtureSnapshot.sessions) {
      this.cursors.set(session.id, BigInt(session.cursor));
    }
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
    if (
      !text ||
      !this.cursors.has(input.sessionId) ||
      this.activeMessages.has(input.sessionId)
    ) {
      return { submissionId: input.submissionId, accepted: false };
    }

    const assistantId = `${input.submissionId}:assistant`;
    this.activeMessages.set(input.sessionId, assistantId);
    this.queue = [
      ...this.queue.filter((step) => step.sessionId !== input.sessionId),
      ...this.script(input.sessionId, assistantId),
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
    });
    return { submissionId: input.submissionId, accepted: true };
  }

  async interrupt(sessionId: string): Promise<ControlReceipt> {
    const messageId = this.activeMessages.get(sessionId);
    if (!messageId) {
      return { accepted: false, reason: "No fixture execution is running." };
    }
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
    if (event.type === "execution.completed") {
      this.activeMessages.delete(step.sessionId);
    }
    return { label: step.label, remaining: this.queue.length };
  }

  remainingFixtureSteps(): number {
    return this.queue.length;
  }

  private script(sessionId: string, messageId: string): ScriptedStep[] {
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
        label: "publish read-only Diff fixture",
        create: (cursor) => ({
          ...envelope(cursor),
          type: "document.available",
          id: `${messageId}:document`,
          document: {
            id: `${messageId}:runbook-diff`,
            title: "GUI B1 runbook.diff",
            kind: "diff",
            sourceLabel: "fixture://changes/gui-b1",
            revision: "fixture-r2",
            content:
              "@@ HarnessGUI fixture @@\n+ UI port isolates presentation\n+ Mock events remain deterministic\n- GUI reads Product internals\n+ GUI consumes accepted values only",
          },
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

export function createMockAppClient(): MockAppClient {
  return new MockAppClient();
}
