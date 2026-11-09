import "./themes/loushang-minimal.css";

export const markdownThemes = [
  { id: "loushang-minimal", name: "Loushang Minimal" },
] as const;

export interface MarkdownPreferences {
  readonly theme: typeof markdownThemes[number]["id"];
}

const storageKey = "loushang.gui.markdown";
const defaults: MarkdownPreferences = { theme: markdownThemes[0].id };

export function readMarkdownPreferences(): MarkdownPreferences {
  try {
    const stored: Partial<MarkdownPreferences> | null = JSON.parse(localStorage.getItem(storageKey) ?? "null");
    return {
      theme: markdownThemes.find((theme) => theme.id === stored?.theme)?.id ?? defaults.theme,
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
