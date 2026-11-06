export type LanguagePreference = "system" | "en-US" | "zh-CN";
export type Language = Exclude<LanguagePreference, "system">;
export const languageStorageKey = "loushang.gui.language";

export function parsePreference(value: string | null): LanguagePreference {
  return value === "en-US" || value === "zh-CN" ? value : "system";
}

function matchLanguage(tag: string): Language | undefined {
  try {
    const locale = new Intl.Locale(tag);
    if (locale.language === "en") return "en-US";
    if (locale.language === "zh" && locale.maximize().script === "Hans") return "zh-CN";
  } catch { /* Ignore malformed platform tags and try the next preference. */ }
  return undefined;
}

export function resolveLanguage(preference: LanguagePreference, languages: readonly string[]): Language {
  if (preference !== "system") return preference;
  for (const tag of languages) {
    const match = matchLanguage(tag);
    if (match) return match;
  }
  return "en-US";
}

export function readPreference(): LanguagePreference {
  try { return parsePreference(localStorage.getItem(languageStorageKey)); }
  catch { return "system"; }
}
