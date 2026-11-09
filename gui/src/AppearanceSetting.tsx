import { useLayoutEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SettingsSelect } from "./SettingsSelect";

type Appearance = "system" | "light" | "dark";
const storageKey = "loushang.gui.appearance";

function readAppearance(): Appearance {
  try {
    const value = localStorage.getItem(storageKey);
    if (value === "light" || value === "dark") return value;
  } catch { /* Settings storage is optional. */ }
  return "system";
}

export function AppearanceSetting() {
  const { t } = useTranslation("shell");
  const [appearance, setAppearance] = useState(readAppearance);
  const [saveFailed, setSaveFailed] = useState(false);
  useLayoutEffect(() => {
    document.documentElement.dataset.appearance = appearance;
    return () => { delete document.documentElement.dataset.appearance; };
  }, [appearance]);

  function change(value: Appearance) {
    setAppearance(value);
    try {
      localStorage.setItem(storageKey, value);
      setSaveFailed(false);
    } catch { setSaveFailed(true); }
  }

  return <div className="settings-preference">
    <SettingsSelect id="app-appearance" label={t("appearance")} value={appearance} onChange={change} options={[
      { value: "system", label: t("system") },
      { value: "light", label: t("appearanceLight") },
      { value: "dark", label: t("appearanceDark") },
    ]} />
    {saveFailed ? <span role="status">{t("appearanceSaveFailed")}</span> : null}
  </div>;
}
