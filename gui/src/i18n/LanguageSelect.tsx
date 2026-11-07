import { useState } from "react";
import { useTranslation } from "react-i18next";
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
  return <div className="language-setting">
    <div>
      <label htmlFor="interface-language">{t("language")}</label>
      <p id="interface-language-description">{t("languageDescription")}</p>
    </div>
    <select id="interface-language" aria-describedby="interface-language-description" value={preference} disabled={pending} onChange={(event) => { void change(event.currentTarget.value); }}>
      <option value="system">{t("system")}</option>
      {/* i18next-instrument-ignore-next-line: language autonym */}
      <option value="zh-CN" lang="zh-CN">简体中文</option>
      {/* i18next-instrument-ignore-next-line: language autonym */}
      <option value="en-US" lang="en-US">English</option>
    </select>
    {saveFailed ? <span role="status">{t("saveFailed")}</span> : null}
  </div>;
}
