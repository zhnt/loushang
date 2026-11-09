import type { ClientSource } from "./model";

export interface SidebarPreferences {
  readonly pinned: readonly string[];
  readonly recent: readonly string[];
}

export function sidebarPreferencesKey(source: ClientSource): string {
  const scope = source.kind === "live" ? `mux:${source.muxSpaceId}` : "fixture";
  return `loushang.gui.sidebar.v1:${scope}`;
}

export function readSidebarPreferences(key: string): SidebarPreferences {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "{}");
    return { pinned: readIds(value?.pinned), recent: readIds(value?.recent) };
  } catch {
    return { pinned: [], recent: [] };
  }
}

export function saveSidebarPreferences(key: string, preferences: SidebarPreferences): void {
  try {
    localStorage.setItem(key, JSON.stringify(preferences));
  } catch {
    // The current window keeps its preferences when storage is unavailable.
  }
}

function readIds(value: unknown): readonly string[] {
  return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === "string" && id.length > 0))] : [];
}
