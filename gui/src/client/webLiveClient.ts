import { invoke, isTauri } from "@tauri-apps/api/core";
import { platform } from "@tauri-apps/plugin-os";
import { validateGoalProgress } from "../../contracts/goalProgress";
import type { ClientSnapshot, ControlReceipt, HarnessClientUiPort, SubmitReceipt } from "./model";
import { projectNativeInitialSnapshot, validateSessionModels } from "./nativeLiveClient";
import { ApprovalResponses } from "./approvalResponses";
import { validateInteractiveGoalRecovery } from "../../contracts/interactiveGoalRecovery";
import { validateInteractiveGoal, validateInteractiveGoalReview } from "../../contracts/interactiveGoal";
import { goalStartReceipt, unknownGoalStart } from "./goalStartReceipt";
import { resourceResult, type ClientDirectoryDraft, type DirectoryPicker } from "./sessionResources";
import { webRequest } from "./hostApi";
import type { WorkspacePreview, WorkspacePreviewRequest, WorkspacePreviewScope } from "./workspacePreview";

/** Same projection/contracts as desktop; authoritative snapshots arrive from AppHost. */
export interface WebLiveClient extends HarnessClientUiPort {
  suspend(): Promise<() => void>;
}

export function createWebLiveClient(workspace: string, connectionId?: string): WebLiveClient {
  const listeners = new Set<(snapshot: ClientSnapshot) => void>();
  const connections = new Set<(state: "disconnected" | "resync-required") => void>();
  let current: ClientSnapshot | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let running: Promise<ClientSnapshot> | null = null;
  let viewId: string | undefined;
  let suspended = false;
  let closing: Promise<unknown> | undefined;
  const call = <T,>(action: string, input = {}): Promise<T> =>
    viewId ? webRequest<T>({ operation: "live", workspace, viewId, action, input }, connectionId)
      : Promise.reject(new Error("connection_failed"));
  const publish = (snapshot: ClientSnapshot) => {
    for (const listener of listeners) listener(snapshot);
  };
  const approvals = new ApprovalResponses(publish);

  function close(notify = true) {
    const released = viewId;
    viewId = undefined;
    current = null;
    approvals.disconnected();
    if (notify) for (const listener of connections) listener("disconnected");
    if (!released) return closing;
    // Close after an in-flight snapshot so it cannot open an orphaned view.
    closing = Promise.allSettled([closing, running]).then(() =>
      webRequest({ operation: "live", workspace, viewId: released, action: "close", input: {} }, connectionId),
    ).catch(() => {});
    return closing;
  }
  const refresh = (): Promise<ClientSnapshot> => {
    if (suspended) return Promise.reject(new Error("connection_suspended"));
    const serial = generation;
    const id = viewId ??= crypto.randomUUID();
    running ??= Promise.resolve(closing).then(() => {
      if (viewId !== id) throw new Error("connection_changed");
      return call<unknown>("snapshot");
    }).then((value) => {
      const projected = projectNativeInitialSnapshot(value);
      if (serial !== generation || viewId !== id || suspended) throw new Error("connection_changed");
      current = projected.source.kind === "live"
        ? { ...projected, source: { ...projected.source, connectionId } } : projected;
      return approvals.project(current);
    }).finally(() => { running = null; });
    return running;
  };
  const poll = async (serial: number) => {
    try {
      if (!suspended) {
        const snapshot = await refresh();
        if (serial === generation) publish(snapshot);
      }
    } catch {
      if (serial === generation && !suspended) {
        // A lost HTTP link invalidates this view even if the worker still
        // has time remaining on its lease.
        void close();
      }
    } finally {
      if (listeners.size && serial === generation) timer = setTimeout(() => void poll(serial), 500);
    }
  };
  function previewScope(input: WorkspacePreviewScope) {
    const source = current?.source;
    if (!viewId || source?.kind !== "live" || source.serviceInstanceId !== input.serviceInstanceId
      || source.connectionEpoch !== input.connectionEpoch) throw new Error("instance_changed");
    const fingerprint = current?.sessions.find((session) => session.id === input.sessionId)?.context.scopeFingerprint;
    if (!fingerprint) throw new Error("permission_denied");
    return fingerprint;
  }

  async function previewWorkspace(input: WorkspacePreviewRequest) {
    const id = viewId;
    const fingerprint = previewScope(input);
    const result = await webRequest<WorkspacePreview>({
      operation: "workspace", action: "preview", path: workspace, fingerprint,
      serviceInstanceId: input.serviceInstanceId, reference: input.reference, base: input.base,
    }, connectionId);
    if (id !== viewId || previewScope(input) !== fingerprint) throw new Error("instance_changed");
    return result;
  }

  const allowClientDirectories = isTauri() && Boolean(connectionId && connectionId !== "local")
    && (platform() === "linux" || platform() === "windows");
  const pickClientDirectory: DirectoryPicker = async (labels) => {
    const value = await invoke<{ id: string; name: string } | null>("pick_client_directory", { connectionId, ...labels });
    if (value && (!/^[a-f0-9]{32}$/.test(value.id) || !value.name)) throw new Error("resource_unavailable");
    return value ? { grantId: value.id, name: value.name } satisfies ClientDirectoryDraft : null;
  };
  const pageHidden = () => { void close(); };
  return {
    snapshot: refresh,
    previewWorkspace,
    async locateWorkspace(input) {
      const id = viewId;
      const fingerprint = previewScope(input);
      const result = await webRequest<{ path: string }>({
        operation: "workspace", action: "locate", fingerprint, serviceInstanceId: input.serviceInstanceId,
      }, connectionId);
      if (id !== viewId || previewScope(input) !== fingerprint) throw new Error("instance_changed");
      return result.path;
    },
    subscribe: () => () => {},
    subscribeSnapshots(listener) {
      listeners.add(listener);
      if (listeners.size === 1) {
        const serial = ++generation;
        timer = setTimeout(() => void poll(serial), 500);
        window.addEventListener("pagehide", pageHidden);
      }
      return () => {
        listeners.delete(listener);
        if (!listeners.size) {
          generation++;
          clearTimeout(timer);
          window.removeEventListener("pagehide", pageHidden);
          void close();
        }
      };
    },
    subscribeConnection(listener) { connections.add(listener); return () => { connections.delete(listener); }; },
    async suspend() {
      suspended = true;
      // Releasing the controller for session creation does not disconnect the Host.
      await close(false);
      return () => { suspended = false; };
    },
    async requestResync() {
      await close(false);
      publish(await refresh());
    },
    respondInteraction(sessionId, interactionId, outcome) {
      return approvals.respond(sessionId, interactionId, (connectionEpoch) =>
        call<ControlReceipt>("respond-interaction", { sessionId, interactionId, outcome, connectionEpoch }),
      );
    },
    async createInteractiveGoal(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-create", input);
      return result === null ? null : validateInteractiveGoal(result);
    },
    async controlInteractiveGoal(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-command", input);
      return result === null ? null : validateInteractiveGoal(result);
    },
    async interactiveGoalRecovery(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-recovery", input);
      return result === null ? null : validateInteractiveGoalRecovery(result);
    },
    async interactiveGoalReview(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-review", input);
      return result === null ? null : validateInteractiveGoalReview(result);
    },
    async submitInteractiveGoalReview(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-review-submit", input);
      return result === null ? null : validateInteractiveGoal(result);
    },
    async interactiveGoalStatus(input) {
      const source = current?.source.kind === "live" ? current.source : null;
      if (source?.serviceInstanceId !== input.serviceInstanceId || source.connectionEpoch !== input.connectionEpoch) return null;
      const result = await call<unknown>("interactive-goal-status", input);
      return result === null ? null : validateInteractiveGoal(result);
    },
    async goalProgress(sessionId, executionId) {
      const serviceInstanceId = current?.source.kind === "live" ? current.source.serviceInstanceId : undefined;
      if (!serviceInstanceId) return null;
      const result = await call<unknown>("goal-progress", { sessionId, executionId, serviceInstanceId });
      return result === null ? null : validateGoalProgress(result, executionId);
    },
    async startGoal(input, expectedInstanceId) {
      const serviceInstanceId = current?.source.kind === "live" ? current.source.serviceInstanceId : undefined;
      const unknown = unknownGoalStart(input.submissionId);
      if (!serviceInstanceId || (expectedInstanceId && expectedInstanceId !== serviceInstanceId)) return unknown;
      const address = { ...input, serviceInstanceId };
      try {
        return goalStartReceipt(await call("goal-start", address), input.submissionId);
      } catch {
        try {
          const recovered = goalStartReceipt(await call("find-submission", address), input.submissionId);
          if (recovered.accepted) return recovered;
        } catch {
          // The original Host may not be reachable.
        }
        return unknown;
      }
    },
    ...(allowClientDirectories ? {
      pickClientDirectory,
      async referenceClientDirectory(sessionId: string, grantId: string) {
        return resourceResult(await call("client-directory-reference", { sessionId, grantId }));
      },
      async revokeClientDirectory(id: string) {
        const value = await webRequest<{ removed: boolean }>({ operation: "revoke-client-directory", id }, connectionId);
        return value.removed;
      },
    } : {}),
    async sessionResource(sessionId, query) {
      return resourceResult(await call("resource", { sessionId, query }));
    },
    async findSubmission(sessionId, submissionId, serviceInstanceId) {
      if (current?.source.kind !== "live" || current.source.serviceInstanceId !== serviceInstanceId) {
        return { accepted: false, submissionId, reason: "submission_outcome_unknown" };
      }
      return call("find-submission", { sessionId, submissionId, serviceInstanceId });
    },
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
