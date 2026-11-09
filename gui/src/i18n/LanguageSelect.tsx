import { useState } from "react";
import { useTranslation } from "react-i18next";
import { SettingsSelect } from "../SettingsSelect";
import { i18n, systemLanguages } from "./index";
import { languageStorageKey, parsePreference, readPreference, resolveLanguage } from "./language";

export function LanguageSelect() {
  const { t } = useTranslation("shell");
  const [preference, setPreference] = useState(readPreference);
  const [pending, setPending] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  async function change(value: string) {
    setPending(true);
    const next = parsePreference(value);
    try {
      const language = resolveLanguage(next, next === "system" ? await systemLanguages() : []);
      await i18n.changeLanguage(language);
      document.documentElement.lang = language;
      setPreference(next);
      try {
        localStorage.setItem(languageStorageKey, next);
        setSaveFailed(false);
      } catch { setSaveFailed(true); }
    } finally { setPending(false); }
  }
  return <div className="settings-preference">
    <SettingsSelect id="interface-language" label={t("language")} description={t("languageDescription")}
      value={preference} busy={pending} onChange={(value) => { void change(value); }} options={[
        { value: "system", label: t("system") },
        { value: "zh-CN", label: "简体中文", lang: "zh-CN" },
        { value: "en-US", label: "English", lang: "en-US" },
      ]} />
    {saveFailed ? <span role="status">{t("saveFailed")}</span> : null}
  </div>;
}
