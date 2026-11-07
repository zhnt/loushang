import type { Ref } from "react";
import { useTranslation } from "react-i18next";
import { LanguageSelect } from "./i18n/LanguageSelect";
import { UiIcon } from "./UiIcon";

export function SettingsDialog({ dialogRef }: { dialogRef: Ref<HTMLDialogElement> }) {
  const { t } = useTranslation("shell");
  return <dialog ref={dialogRef} className="settings-dialog" aria-labelledby="settings-title">
    <header className="settings-header">
      <h2 id="settings-title">{t("settings")}</h2>
      <form method="dialog">
        <button type="submit" className="icon-close" aria-label={t("closeSettings")}><UiIcon name="close" /></button>
      </form>
    </header>
    <section className="settings-section" aria-labelledby="settings-general">
      <h3 id="settings-general">{t("generalSettings")}</h3>
      <LanguageSelect />
    </section>
  </dialog>;
}
