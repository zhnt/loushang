import "./themes/loushang-minimal.css";

export const markdownThemes = [
  { id: "loushang-minimal", name: "Loushang Minimal" },
] as const;

export type MarkdownScheme = "system" | "light" | "dark";

export interface MarkdownPreferences {
  readonly theme: typeof markdownThemes[number]["id"];
  readonly scheme: MarkdownScheme;
}

const storageKey = "loushang.gui.markdown";
const defaults: MarkdownPreferences = { theme: markdownThemes[0].id, scheme: "system" };

export function readMarkdownPreferences(): MarkdownPreferences {
  try {
    const stored: Partial<MarkdownPreferences> | null = JSON.parse(localStorage.getItem(storageKey) ?? "null");
    return {
      theme: markdownThemes.find((theme) => theme.id === stored?.theme)?.id ?? defaults.theme,
      scheme: stored?.scheme === "light" || stored?.scheme === "dark" ? stored.scheme : defaults.scheme,
    };
  } catch {
    return defaults;
  }
}

export function saveMarkdownPreferences(preferences: MarkdownPreferences): boolean {
  try {
    localStorage.setItem(storageKey, JSON.stringify(preferences));
    return true;
  } catch {
    return false;
  }
}
