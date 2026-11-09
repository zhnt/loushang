import { useState } from "react";
import { useTranslation } from "react-i18next";
import { SettingsSelect } from "../SettingsSelect";
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

  return <div className="settings-preference">
    <SettingsSelect id="markdown-theme" label={t("markdownTheme")} description={t("markdownThemeDescription")}
      value={preferences.theme} onChange={(theme) => update({ theme })}
      options={markdownThemes.map(({ id, name }) => ({ value: id, label: name }))} />
    {saveFailed ? <span role="status">{t("markdownSaveFailed")}</span> : null}
  </div>;
}
