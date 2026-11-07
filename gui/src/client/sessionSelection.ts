import type { ClientSnapshot, ClientSource } from "./model";

export function liveSelectionKey(source: ClientSource): string | null {
  // AppHost allocates this opaque ID per mux and restores it from continuity
  // storage. Service instance IDs and mux names do not identify that lifetime.
  return source.kind === "live" ? `loushang.gui.selected-session.v1:${source.muxSpaceId}` : null;
}

export function restoreSessionSelection(snapshot: ClientSnapshot): ClientSnapshot {
  const key = liveSelectionKey(snapshot.source);
  if (!key || snapshot.connection !== "connected") return snapshot;
  try {
    const selectedSessionId = localStorage.getItem(key);
    if (selectedSessionId && snapshot.sessions.some((session) => session.id === selectedSessionId)) {
      return { ...snapshot, selectedSessionId };
    }
  } catch {
    // Selection remains usable when local storage is unavailable.
  }
  return snapshot;
}

export function rememberSessionSelection(key: string, sessionId: string): void {
  try {
    localStorage.setItem(key, sessionId);
  } catch {
    // Storage failures must not interrupt a live conversation.
  }
}
