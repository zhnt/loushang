import type { ClientSnapshot, ControlReceipt, PendingApproval } from "./model";

type Decision = { status: "submitting" | "processed" | "unavailable" };
const key = (sessionId: string, interactionId: string) => JSON.stringify([sessionId, interactionId]);

function connectionKey(snapshot: ClientSnapshot | null): string {
  const source = snapshot?.source;
  return source?.kind === "live" ? JSON.stringify([source.serviceInstanceId, source.connectionEpoch]) : "";
}

export class ApprovalResponses {
  private readonly decisions = new Map<string, Decision>();
  private current: ClientSnapshot | null = null;

  constructor(private readonly publish: (snapshot: ClientSnapshot) => void) {}

  project(value: ClientSnapshot): ClientSnapshot {
    if (connectionKey(this.current) !== connectionKey(value)) this.decisions.clear();
    this.current = value;
    const active = new Set<string>();
    const sessions = value.sessions.map((session) => {
      if (!session.pendingApprovals?.length) return session;
      const pendingApprovals = session.pendingApprovals.map((approval): PendingApproval => {
        const id = key(session.id, approval.interactionId);
        active.add(id);
        const decision = this.decisions.get(id);
        return decision ? { ...approval, status: decision.status } : approval;
      });
      return { ...session, pendingApprovals };
    });
    for (const id of this.decisions.keys()) {
      if (!active.has(id)) this.decisions.delete(id);
    }
    return { ...value, sessions };
  }

  disconnected() {
    this.current = null;
    this.decisions.clear();
  }

  async respond(
    sessionId: string,
    interactionId: string,
    send: (connectionEpoch: string) => Promise<ControlReceipt>,
  ): Promise<ControlReceipt> {
    const snapshot = this.current;
    const id = key(sessionId, interactionId);
    const approvals = snapshot?.sessions.find((session) => session.id === sessionId)?.pendingApprovals;
    if (snapshot?.source.kind !== "live" || this.decisions.has(id)
      || !approvals?.some((approval) => approval.interactionId === interactionId)) {
      return { accepted: false, reason: "operation_unavailable" };
    }
    const decision: Decision = { status: "submitting" };
    this.decisions.set(id, decision);
    this.publish(this.project(snapshot));
    const receipt = await send(snapshot.source.connectionEpoch)
      .catch(() => ({ accepted: false, reason: "connection_failed" }));
    this.markSettled(id, decision, receipt.accepted);
    return receipt;
  }

  private markSettled(id: string, decision: Decision, accepted: boolean) {
    if (this.current && this.decisions.get(id) === decision) {
      decision.status = accepted ? "processed" : "unavailable";
      this.publish(this.project(this.current));
    }
  }
}
