export interface SessionOperationScope {
  readonly sessionId: string;
  readonly serviceInstanceId: string;
  readonly connectionEpoch: string;
}

export type SessionMutation =
  | { readonly action: "setTool"; readonly name: string; readonly active: boolean }
  | { readonly action: "resetTools" }
  | { readonly action: "compact" };

export type SessionOperation =
  | { readonly action: "info" | "tools" }
  | (SessionMutation & { readonly submissionId: string })
  | { readonly action: "lookup"; readonly submissionId: string }
  | { readonly action: "interrupt"; readonly executionId: string };

interface Tool {
  readonly name: string;
  readonly description?: string;
  readonly allowed?: boolean;
  readonly active: boolean;
}

export interface SessionCommandData {
  readonly status?: string;
  readonly message?: string;
  readonly truncated?: boolean;
  readonly available_tools?: readonly Tool[];
  readonly session?: {
    readonly session_name?: string;
    readonly session_id: string;
    readonly active_tool_count: number;
    readonly is_compacting: boolean;
    readonly context?: {
      readonly tokens?: number;
      readonly context_window?: number;
      readonly accuracy?: string;
      readonly structural_envelope_status?: string;
    };
    readonly compaction?: {
      readonly last_tokens_before?: number;
      readonly last_tokens_after?: number;
    };
  };
}

export type SessionOperationReply = {
  readonly error?: string;
  readonly data?: SessionCommandData;
  readonly executionId?: string;
  readonly accepted?: boolean;
  readonly state?: {
    readonly executionId: string;
    readonly status: "accepted" | "running" | "succeeded" | "failed" | "interrupted";
    readonly interruptRequested: boolean;
    readonly outcome: { readonly errorCode: string | null } | null;
  };
} | null;

export type SessionOperationPort = (
  scope: SessionOperationScope, operation: SessionOperation,
) => Promise<SessionOperationReply>;

export interface PendingSessionMutation {
  readonly action: SessionMutation["action"];
  readonly id: string;
}
