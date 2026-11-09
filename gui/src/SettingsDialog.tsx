import type { ReactNode, Ref } from "react";
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
    {account ? <section className="settings-section" aria-labelledby="settings-account">
      <h3 id="settings-account">{t("offlineAccount")}</h3>
      <dl className="detail-list">
        <div><dt>{t("accountName")}</dt><dd>{account.name}</dd></div>
        {account.id ? <div><dt>{t("accountId")}</dt><dd>{account.id}</dd></div> : null}
      </dl>
    </section> : null}
    {hostSettings ? <section className="settings-section">{hostSettings}</section> : null}
  </dialog>;
}
