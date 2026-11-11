import type { ClientSnapshot, ClientSource } from "./model";
import { readSidebarPreferences, updateSidebarPreferences, sidebarPreferencesKey } from "./sidebarPreferences";

export function liveSelectionKey(source: ClientSource): string | null {
  return source.kind === "live" ? sidebarPreferencesKey(source) : null;
}
export function restoreSessionSelection(snapshot: ClientSnapshot): ClientSnapshot {
  const key = liveSelectionKey(snapshot.source);
  if (!key || snapshot.connection !== "connected") return snapshot;
  const selectedSessionId = readSidebarPreferences(key).selected;
  return selectedSessionId && snapshot.sessions.some((session) => session.id === selectedSessionId)
    ? { ...snapshot, selectedSessionId } : snapshot;
}
export async function rememberSessionSelection(key: string, sessionId: string): Promise<void> {
  await updateSidebarPreferences(key, "visit", sessionId).catch(() => {});
}
