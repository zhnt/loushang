import { useEffect, useState } from "react";
import type { ClientSnapshot, DraftBinding, HarnessClientUiPort, SessionModels, SessionSnapshot, SubmitReceipt, ThinkingLevel } from "./client/model";

export interface DraftTarget {
  readonly key: string;
  readonly hostKey: string;
  readonly workspace: string | null;
  readonly loadModels?: (modelId?: string) => Promise<SessionModels>;
  readonly create: (continuityId: string) => Promise<DraftBinding | null>;
}

type DraftStatus = "ready" | "creating" | "sending" | "createFailed" | "createUnknown"
  | "createSyncFailed" | FirstModelFailure | "firstSubmitRejected" | "firstSubmissionUnknown";
type FirstModelFailure = "firstModelUnavailable" | "firstThinkingUnavailable";

interface Draft {
  readonly id: string;
  readonly target: DraftTarget;
  readonly text: string;
  readonly modelId?: string;
  readonly thinking?: SessionModels["thinking"];
  readonly visible: boolean;
  readonly status: DraftStatus;
  readonly binding?: DraftBinding;
  readonly unconfirmed?: { id: string; instanceId?: string };
}

type Observation = { client: HarnessClientUiPort; snapshot: ClientSnapshot };
type PublishedSession = { snapshot: ClientSnapshot; session: SessionSnapshot };
type Accepted = (published: PublishedSession, text: string, receipt: SubmitReceipt, select: boolean) => void;

function publishedSession(observation: Observation | null, binding: DraftBinding, id: string): PublishedSession | null {
  if (observation?.client !== binding.client || observation.snapshot.connection !== "connected") return null;
  const { snapshot } = observation;
  const session = snapshot.sessions.find((session) => session.context.continuityId === id
    && (binding.sessionId === undefined || session.id === binding.sessionId));
  return session ? { snapshot, session } : null;
}

export function isSendingDraft(draft: Draft | null): draft is Draft & { status: "creating" | "sending" } {
  return draft?.status === "creating" || draft?.status === "sending";
}

export function canSubmitDraft(draft: Draft | null): draft is Draft {
  return Boolean(draft?.visible && draft.text.trim() && draft.status !== "firstSubmissionUnknown"
    && (draft.status !== "createUnknown" || draft.binding));
}

class SessionCreation {
  private current: Draft | null = null;
  private readonly drafts = new Map<string, Draft>();
  private observed: Observation | null = null;
  private waiter: ((observation: Observation | null) => void) | null = null;
  private inFlight = false;

  constructor(private readonly publish: (state: { current: Draft | null; drafts: readonly Draft[] }) => void) {}

  private save(next: Draft | null) {
    if (next) this.drafts.set(next.target.key, next);
    else if (this.current) this.drafts.delete(this.current.target.key);
    this.current = next;
    this.publish({ current: next, drafts: [...this.drafts.values()] });
  }

  dispose() {
    this.current = null;
    this.drafts.clear();
    this.waiter?.(null);
  }

  observe = (client: HarnessClientUiPort, snapshot: ClientSnapshot | null) => {
    this.observed = snapshot ? { client, snapshot } : null;
    if (snapshot) this.waiter?.(this.observed);
  };

  private waitForSession(binding: DraftBinding, id: string): Promise<PublishedSession | null> {
    const existing = publishedSession(this.observed, binding, id);
    if (existing) return Promise.resolve(existing);
    return new Promise((resolve) => {
      const finish = (result: PublishedSession | null) => {
        window.clearTimeout(timer);
        this.waiter = null;
        resolve(result);
      };
      const timer = window.setTimeout(() => finish(null), 15_000);
      this.waiter = (observation) => {
        const result = publishedSession(observation, binding, id);
        if (!observation || result) finish(result);
      };
      void binding.refresh?.().catch(() => {
        // An automatic reconnect may still publish the Session.
      });
    });
  }

  open(target: DraftTarget) {
    if (this.inFlight) return;
    const previous = this.drafts.get(target.key);
    this.save(previous ? { ...previous, target, visible: true } : {
      id: `gui-draft-${crypto.randomUUID()}`, target, text: "", visible: true, status: "ready",
    });
  }

  hide = () => {
    if (this.current?.visible) this.save({ ...this.current, visible: false });
    this.waiter?.(null);
  };

  change(text: string) {
    if (this.current?.visible && !this.inFlight) this.save({ ...this.current, text });
  }

  selectModel(target: DraftTarget, id: string, thinking?: SessionModels["thinking"]) {
    if (!this.current?.visible || this.inFlight || this.current.target !== target) return false;
    this.save({ ...this.current, modelId: id, thinking });
    return true;
  }

  private update(id: string, patch: Partial<Draft>) {
    if (this.current?.id === id) this.save({ ...this.current, ...patch });
  }

  private async resolveBinding(input: Draft): Promise<PublishedSession | null> {
    const binding = input.binding ?? await input.target.create(input.id);
    if (!binding) {
      this.update(input.id, { status: "createFailed" });
      return null;
    }
    this.update(input.id, { binding });
    const shown = this.current?.visible && binding.show(binding.sessionId);
    const published = shown ? await this.waitForSession(binding, input.id) : null;
    if (published) {
      this.update(input.id, { binding: { ...binding, sessionId: published.session.id } });
    } else {
      this.update(input.id, { status: binding.sessionId ? "createSyncFailed" : "createUnknown" });
    }
    return published;
  }

  async submit(onAccepted: Accepted, modelId?: string, level?: ThinkingLevel) {
    const input = this.current;
    if (this.inFlight || !canSubmitDraft(input)) return;
    this.inFlight = true;
    this.update(input.id, { status: input.binding?.sessionId ? "sending" : "creating" });
    try {
      const published = await this.resolveBinding(input);
      if (published) await this.send(input, published, onAccepted, modelId, level);
    } catch {
      this.update(input.id, { status: "createUnknown" });
    } finally {
      this.inFlight = false;
    }
  }

  private async send(input: Draft, published: PublishedSession, onAccepted: Accepted, modelId?: string, level?: ThinkingLevel) {
    const binding = this.current?.binding;
    if (!this.current?.visible || !binding?.show(published.session.id)) {
      this.update(input.id, { status: "createSyncFailed" });
      return;
    }
    this.update(input.id, { status: "sending" });
    if (modelId && !await this.applyFirstModel(binding, published.session.id, input.id, modelId, level)) return;
    const receipt = await sendDraft(binding.client, published.session.id, input.text);
    if (!receipt.accepted) {
      const unknown = receipt.reason === "submission_outcome_unknown";
      const instanceId = published.snapshot.source.kind === "live" ? published.snapshot.source.serviceInstanceId : undefined;
      this.update(input.id, {
        status: unknown ? "firstSubmissionUnknown" : "firstSubmitRejected",
        unconfirmed: unknown ? { id: receipt.submissionId, instanceId } : undefined,
      });
      return;
    }
    if (this.current?.id === input.id) {
      onAccepted(published, input.text, receipt, this.current.visible);
      this.save(null);
    }
  }

  async check(onAccepted: Accepted) {
    const draft = this.current;
    const pending = draft?.unconfirmed;
    const binding = draft?.binding;
    if (!draft?.visible || !binding || !pending) return;
    const published = publishedSession(this.observed, binding, draft.id);
    const id = binding.sessionId;
    if (published && id && pending.instanceId && binding.client.findSubmission) {
      const receipt = await binding.client.findSubmission(id, pending.id, pending.instanceId).catch(() => null);
      if (receipt?.accepted && receipt.submissionId === pending.id && this.current?.id === draft.id) {
        onAccepted(published, draft.text, receipt, this.current.visible);
        this.save(null);
        return;
      }
    }
    await binding.client.requestResync?.().catch(() => {});
  }

  private async applyFirstModel(binding: DraftBinding, sessionId: string, draftId: string, modelId: string, level?: ThinkingLevel) {
    const failure = await confirmFirstModel(binding.client, sessionId, modelId, level);
    if (failure) {
      this.update(draftId, { status: failure });
      return false;
    }
    if (this.current?.id === draftId && this.current.visible) return true;
    this.update(draftId, { status: "createSyncFailed" });
    return false;
  }
}

export function useSessionCreation(onAccepted: Accepted) {
  const [{ current: draft, drafts }, publish] = useState<{ current: Draft | null; drafts: readonly Draft[] }>({
    current: null, drafts: [],
  });
  const [creation] = useState(() => new SessionCreation(publish));
  useEffect(() => () => creation.dispose(), [creation]);
  return {
    draft, drafts, observe: creation.observe, hide: creation.hide,
    open: (target: DraftTarget) => creation.open(target),
    change: (text: string) => creation.change(text),
    selectModel: (target: DraftTarget, id: string, thinking?: SessionModels["thinking"]) => creation.selectModel(target, id, thinking),
    check: () => creation.check(onAccepted),
    submit: (modelId?: string, level?: ThinkingLevel) => creation.submit(onAccepted, modelId, level),
  };
}

async function confirmFirstModel(
  client: HarnessClientUiPort, sessionId: string, modelId: string, level?: ThinkingLevel,
): Promise<FirstModelFailure | null> {
  let failure: FirstModelFailure = "firstModelUnavailable";
  try {
    let current = await client.sessionModels?.(sessionId);
    if (current?.currentId !== modelId) {
      if (!current?.models.some((model) => model.id === modelId)) return failure;
      current = await client.selectModel?.(sessionId, modelId);
      if (current?.currentId !== modelId) return failure;
    }
    if (level === undefined || current.thinking?.currentLevel === level) return null;
    failure = "firstThinkingUnavailable";
    if (!current.thinking?.availableLevels.includes(level)) return failure;
    const selected = await client.selectModel?.(sessionId, modelId, level);
    return selected?.currentId === modelId && selected.thinking?.currentLevel === level ? null : failure;
  } catch {
    return failure;
  }
}

async function sendDraft(client: HarnessClientUiPort, sessionId: string, text: string): Promise<SubmitReceipt> {
  const submissionId = `gui-${crypto.randomUUID()}`;
  try {
    return await client.submitText({ sessionId, submissionId, text });
  } catch {
    return { accepted: false, reason: "submission_outcome_unknown", submissionId };
  }
}
