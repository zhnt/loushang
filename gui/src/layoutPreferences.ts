interface LayoutPreferences {
  readonly sidebarOpen: boolean;
}

const storageKey = "loushang.gui.layout.v1";
const defaults: LayoutPreferences = { sidebarOpen: false };

export function readLayoutPreferences(): LayoutPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) ?? "null") as Partial<LayoutPreferences> | null;
    return {
      sidebarOpen: typeof stored?.sidebarOpen === "boolean" ? stored.sidebarOpen : defaults.sidebarOpen,
    };
  } catch {
    return defaults;
  }
}

export function saveLayoutPreferences(preferences: LayoutPreferences): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(preferences));
  } catch {
    // Layout changes remain available when local storage is blocked.
  }
}
