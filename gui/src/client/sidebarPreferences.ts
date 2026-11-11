import type { ClientSource } from "./model";
import { sharedSettings, webRequest } from "./hostApi";

export interface SidebarPreferences {
  readonly pinned: readonly string[];
  readonly recent: readonly string[];
  readonly selected?: string;
}
const connections = new Map<string, string>();
const scopes = new Map<string, string>();
const cache = new Map<string, SidebarPreferences>();
export function sidebarPreferencesKey(source: ClientSource): string {
  const scope = source.kind === "live" ? `mux:${source.muxSpaceId}` : "fixture";
  const key = source.kind === "live" && source.connectionId ? `${source.connectionId}/${scope}` : scope;
  scopes.set(key, scope);
  if (source.kind === "live" && source.connectionId) connections.set(key, source.connectionId);
  return key;
}
export function readSidebarPreferences(key: string): SidebarPreferences {
  return cache.get(key) ?? { pinned: [], recent: [] };
}
// Test clients can use the same view without writing persistent product state.
export function saveSidebarPreferences(key: string, value: SidebarPreferences): void { cache.set(key, value); }
export async function updateSidebarPreferences(key: string, action = "read", session = ""): Promise<SidebarPreferences> {
  if (key === "fixture") return readSidebarPreferences(key);
  const request = { operation: "preferences", scope: scopes.get(key) ?? key, action, session };
  const id = connections.get(key);
  const value = id ? await webRequest<SidebarPreferences>(request, id) : await sharedSettings<SidebarPreferences>(request);
  if (!value || !Array.isArray(value.pinned) || !Array.isArray(value.recent)
    || ![...value.pinned, ...value.recent].every((id) => typeof id === "string")) throw new Error("invalid_preferences");
  cache.set(key, value);
  return value;
}
