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

export type DocumentKind = "markdown" | "text" | "diff";

export interface ReadonlyDocument {
  readonly id: string;
  readonly title: string;
  readonly kind: DocumentKind;
  readonly sourceLabel: string;
  readonly revision: string;
  readonly content: string;
}

export interface SessionSnapshot {
  readonly id: string;
  readonly title: string;
  readonly status: SessionStatus;
  readonly cursor: string;
  readonly context: ContextIdentity;
  readonly messages: readonly ConversationMessage[];
  readonly documents: readonly ReadonlyDocument[];
}

export interface CapabilitySummary {
  readonly name: "workspace" | "changes" | "artifacts";
  readonly version: string | null;
  readonly availability: "fixture" | "unavailable";
}

export interface ClientSnapshot {
  readonly generation: string;
  readonly connection: ConnectionState;
  readonly fixtureLabel: string;
  readonly capabilities: readonly CapabilitySummary[];
  readonly sessions: readonly SessionSnapshot[];
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
