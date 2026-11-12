import type { ClientSnapshot, HarnessClientUiPort, SubmitReceipt } from "./model";
import { projectNativeInitialSnapshot, validateSessionModels } from "./nativeLiveClient";
import { webRequest } from "./hostApi";

/** Same projection/contracts as desktop; authoritative snapshots arrive from AppHost. */
export function createWebLiveClient(workspace: string, connectionId?: string): HarnessClientUiPort {
  const listeners = new Set<(snapshot: ClientSnapshot) => void>();
  const connections = new Set<(state: "disconnected" | "resync-required") => void>();
  let current: ClientSnapshot | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let running: Promise<ClientSnapshot> | null = null;
  const call = <T,>(action: string, input = {}): Promise<T> => webRequest<T>({ operation: "live", workspace, action, input }, connectionId);
  const refresh = (): Promise<ClientSnapshot> => {
    running ??= call<unknown>("snapshot").then((value) => {
      const projected = projectNativeInitialSnapshot(value);
      current = projected.source.kind === "live"
        ? { ...projected, source: { ...projected.source, connectionId } } : projected;
      return current;
    }).finally(() => { running = null; });
    return running;
  };
  const poll = async (serial: number) => {
    try {
      const snapshot = await refresh();
      if (serial === generation) for (const listener of listeners) listener(snapshot);
    } catch {
      if (serial === generation) for (const listener of connections) listener("disconnected");
    } finally {
      if (listeners.size && serial === generation) timer = setTimeout(() => void poll(serial), 500);
    }
  };
  return {
    snapshot: refresh,
    subscribe: () => () => {},
    subscribeSnapshots(listener) {
      listeners.add(listener);
      if (listeners.size === 1) { const serial = ++generation; timer = setTimeout(() => void poll(serial), 500); }
      return () => { listeners.delete(listener); if (!listeners.size) { generation++; clearTimeout(timer); } };
    },
    subscribeConnection(listener) { connections.add(listener); return () => { connections.delete(listener); }; },
    async requestResync() { const snapshot = await refresh(); for (const listener of listeners) listener(snapshot); },
    async submitText(input) {
      const serviceInstanceId = current?.source.kind === "live" ? current.source.serviceInstanceId : undefined;
      try {
        return await call("submit", { ...input, serviceInstanceId });
      } catch {
        if (serviceInstanceId) {
          try {
            return await call<SubmitReceipt>("find-submission", {
              sessionId: input.sessionId, submissionId: input.submissionId, serviceInstanceId,
            });
          } catch {
            // The original AppHost may no longer be reachable.
          }
        }
        return { submissionId: input.submissionId, accepted: false, reason: "submission_outcome_unknown" };
      }
    },
    interrupt(sessionId) {
      const executionId = current?.sessions.find((session) => session.id === sessionId)?.execution?.id;
      return executionId ? call("interrupt", { sessionId, executionId }) : Promise.resolve({ accepted: false });
    },
    createSession: (input) => call("create", input),
    async sessionModels(sessionId) { return validateSessionModels(await call("models", { sessionId })); },
    async selectModel(sessionId, modelId, thinkingLevel) {
      return validateSessionModels(await call("select-model", { sessionId, modelId, thinkingLevel }));
    },
  };
}
