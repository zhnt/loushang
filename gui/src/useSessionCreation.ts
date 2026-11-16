import { useEffect, useState } from "react";
import type { ClientSnapshot, DraftBinding, HarnessClientUiPort, SessionSnapshot, SubmitReceipt } from "./client/model";

export interface DraftTarget {
  readonly key: string;
  readonly hostKey: string;
  readonly create: (continuityId: string) => Promise<DraftBinding | null>;
}

type DraftStatus = "ready" | "creating" | "sending" | "createFailed" | "createUnknown"
  | "createSyncFailed" | "firstSubmitRejected" | "firstSubmissionUnknown";

interface Draft {
  readonly id: string;
  readonly target: DraftTarget;
  readonly text: string;
  readonly visible: boolean;
  readonly status: DraftStatus;
  readonly binding?: DraftBinding;
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

export function canSubmitDraft(draft: Draft | null): draft is Draft {
  return Boolean(draft?.visible && draft.text.trim() && draft.status !== "firstSubmissionUnknown"
    && (draft.status !== "createUnknown" || draft.binding));
}

class SessionCreation {
  private current: Draft | null = null;
  private observed: Observation | null = null;
  private waiter: ((observation: Observation | null) => void) | null = null;
  private inFlight = false;

  constructor(private readonly setDraft: (draft: Draft | null) => void) {}

  private save(next: Draft | null) {
    this.current = next;
    this.setDraft(next);
  }

  dispose() {
    this.current = null;
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
    if (this.current?.target.key === target.key) {
      this.save({ ...this.current, visible: true });
    } else if (!this.inFlight) {
      this.save({ id: `gui-draft-${crypto.randomUUID()}`, target, text: "", visible: true, status: "ready" });
    }
  }

  hide = () => {
    if (this.current?.visible) this.save({ ...this.current, visible: false });
    this.waiter?.(null);
  };

  change(text: string) {
    if (this.current?.visible && !this.inFlight) this.save({ ...this.current, text });
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

  async submit(onAccepted: Accepted) {
    const input = this.current;
    if (this.inFlight || !canSubmitDraft(input)) return;
    this.inFlight = true;
    this.update(input.id, { status: input.binding?.sessionId ? "sending" : "creating" });
    try {
      const published = await this.resolveBinding(input);
      if (published) await this.send(input, published, onAccepted);
    } catch {
      this.update(input.id, { status: "createUnknown" });
    } finally {
      this.inFlight = false;
    }
  }

  private async send(input: Draft, published: PublishedSession, onAccepted: Accepted) {
    const binding = this.current?.binding;
    if (!this.current?.visible || !binding?.show(published.session.id)) {
      this.update(input.id, { status: "createSyncFailed" });
      return;
    }
    this.update(input.id, { status: "sending" });
    const receipt = await sendDraft(binding.client, published.session.id, input.text);
    if (!receipt.accepted) {
      this.update(input.id, { status: receipt.reason === "submission_outcome_unknown" ? "firstSubmissionUnknown" : "firstSubmitRejected" });
      return;
    }
    if (this.current?.id === input.id) {
      onAccepted(published, input.text, receipt, this.current.visible);
      this.save(null);
    }
  }
}

export function useSessionCreation(onAccepted: Accepted) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [creation] = useState(() => new SessionCreation(setDraft));
  useEffect(() => () => creation.dispose(), [creation]);
  return {
    draft, observe: creation.observe, hide: creation.hide,
    open: (target: DraftTarget) => creation.open(target),
    change: (text: string) => creation.change(text),
    submit: () => creation.submit(onAccepted),
  };
}

async function sendDraft(client: HarnessClientUiPort, sessionId: string, text: string): Promise<SubmitReceipt> {
  const submissionId = `gui-${crypto.randomUUID()}`;
  try {
    return await client.submitText({ sessionId, submissionId, text });
  } catch {
    return { accepted: false, reason: "submission_outcome_unknown", submissionId };
  }
}
