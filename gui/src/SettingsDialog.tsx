import { useState, type ReactNode, type Ref } from "react";
import { useTranslation } from "react-i18next";
import { LanguageSelect } from "./i18n/LanguageSelect";
import { UiIcon } from "./UiIcon";
import type { OfflineAccount } from "./client/offlineAccount";

export function SettingsDialog({ dialogRef, account, hostSettings }: {
  dialogRef: Ref<HTMLDialogElement>;
  account?: OfflineAccount | null;
  hostSettings?: ReactNode;
}) {
  const { t } = useTranslation("shell");
  const [page, setPage] = useState<"general" | "host">("general");
  const hostPage = page === "host" && Boolean(hostSettings);
  return <dialog ref={dialogRef} className="settings-dialog" aria-labelledby="settings-title" onClose={() => setPage("general")}>
    <header className="settings-header">
      <h2 id="settings-title">{t("settings")}</h2>
      <form method="dialog">
        <button type="submit" className="icon-close" aria-label={t("closeSettings")}><UiIcon name="close" /></button>
      </form>
    </header>
    <div className="settings-layout">
      <nav className="settings-nav" aria-label={t("settingsNavigation")}>
        <button type="button" aria-current={!hostPage ? "page" : undefined} onClick={() => setPage("general")}>
          <UiIcon name="settings" />{t("generalSettings")}
        </button>
        {hostSettings ? <button type="button" aria-current={hostPage ? "page" : undefined} onClick={() => setPage("host")}>
          <UiIcon name="host" />{t("hostSettings")}
        </button> : null}
      </nav>
      <section className="settings-content" aria-labelledby="settings-general" hidden={hostPage}>
        <h3 id="settings-general">{t("generalSettings")}</h3>
        <LanguageSelect />
        {account ? <section className="settings-card" aria-labelledby="settings-account">
          <h4 id="settings-account">{t("offlineAccount")}</h4>
          <dl className="detail-list">
            <div><dt>{t("accountName")}</dt><dd>{account.name}</dd></div>
            {account.id ? <div><dt>{t("accountId")}</dt><dd>{account.id}</dd></div> : null}
          </dl>
        </section> : null}
      </section>
      {hostSettings ? <section className="settings-content" aria-label={t("hostSettings")} hidden={!hostPage}>
        {hostSettings}
      </section> : null}
    </div>
  </dialog>;
}
