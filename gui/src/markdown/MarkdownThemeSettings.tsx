import { useState } from "react";
import { useTranslation } from "react-i18next";
import { markdownThemes, saveMarkdownPreferences, type MarkdownPreferences } from "./preferences";

export function MarkdownThemeSettings({ preferences, onChange }: {
  readonly preferences: MarkdownPreferences;
  readonly onChange: (next: MarkdownPreferences) => void;
}) {
  const { t } = useTranslation("shell");
  const [saveFailed, setSaveFailed] = useState(false);

  function update(next: MarkdownPreferences) {
    onChange(next);
    setSaveFailed(!saveMarkdownPreferences(next));
  }

  return <>
    <div className="settings-preference">
      <div>
        <label htmlFor="markdown-theme">{t("markdownTheme")}</label>
        <p id="markdown-theme-description">{t("markdownThemeDescription")}</p>
      </div>
      <select id="markdown-theme" aria-describedby="markdown-theme-description" value={preferences.theme}
        onChange={(event) => {
          const selected = markdownThemes.find((theme) => theme.id === event.currentTarget.value);
          if (selected) update({ ...preferences, theme: selected.id });
        }}>
        {markdownThemes.map((theme) => <option key={theme.id} value={theme.id}>{theme.name}</option>)}
      </select>
    </div>
    <div className="settings-preference">
      <label htmlFor="markdown-scheme">{t("markdownAppearance")}</label>
      <select id="markdown-scheme" value={preferences.scheme} onChange={(event) => {
        const scheme = event.currentTarget.value;
        if (scheme === "system" || scheme === "light" || scheme === "dark") update({ ...preferences, scheme });
      }}>
        <option value="system">{t("system")}</option>
        <option value="light">{t("markdownLight")}</option>
        <option value="dark">{t("markdownDark")}</option>
      </select>
      {saveFailed ? <span role="status">{t("markdownSaveFailed")}</span> : null}
    </div>
  </>;
}
