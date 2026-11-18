import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CopyButton } from "./CopyButton";
import { UiIcon } from "./UiIcon";
import type { OfflineAccount } from "./client/offlineAccount";

export function AccountMenu({ compact = false, account, onSettings }: {
  compact?: boolean;
  account?: OfflineAccount | null;
  onSettings: () => void;
}) {
  const { t } = useTranslation("shell");
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const settings = useRef<HTMLButtonElement>(null);
  const details = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;
    settings.current?.focus({ preventScroll: true });
    function dismissOutside(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    }
    function dismissOnWindowBlur() { setOpen(false); }
    document.addEventListener("pointerdown", dismissOutside);
    window.addEventListener("blur", dismissOnWindowBlur);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      window.removeEventListener("blur", dismissOnWindowBlur);
    };
  }, [open]);

  function dismiss() {
    setOpen(false);
    trigger.current?.focus({ preventScroll: true });
  }

  return <div ref={root} className={compact ? "account-menu account-menu-compact" : "account-menu"}
    onBlur={(event) => {
      if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}
    onKeyDown={(event) => {
      if (open && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      }
    }}>
    <button ref={trigger} type="button" className={compact ? "account-avatar-button" : "rail-footer"}
      aria-label={t("accountMenu")} aria-expanded={open} aria-controls={open ? id : undefined}
      title={account?.name ?? t("accountMenu")} onClick={() => setOpen(!open)}>
      <span className="user-avatar" aria-hidden="true">{account ? Array.from(account.name.trim())[0].toLocaleUpperCase() : <UiIcon name="account" />}</span>
      {compact ? null : <>
        <span className="account-label"><strong>{account?.name ?? t("accountMenu")}</strong>{account ? <small>{t("offlineAccount")}</small> : null}</span>
        <span aria-hidden="true">⋯</span>
      </>}
    </button>
    {open ? <div id={id} className="account-popover">
      {account ? <section className="account-popover-profile" aria-label={t("offlineAccount")}>
        <button type="button" className="account-profile-button" aria-haspopup="dialog" aria-controls={`${id}-details`}
          onClick={() => { dismiss(); details.current?.showModal(); }}>
          <span className="account-label"><strong>{account.name}</strong><small>{t("offlineAccount")}</small></span>
          <span className="sr-only">{t("accountDetails")}</span>
          <UiIcon name="chevron-right" />
        </button>
      </section> : null}
      <button ref={settings} type="button" onClick={() => { dismiss(); onSettings(); }}>
        <UiIcon name="settings" />
        {t("settings")}
      </button>
    </div> : null}
    {account ? <dialog ref={details} id={`${id}-details`} className="frame-dialog account-details-dialog"
      aria-labelledby={`${id}-details-title`} onClose={() => trigger.current?.focus({ preventScroll: true })}>
      <header className="settings-header">
        <h2 id={`${id}-details-title`}>{t("accountDetails")}</h2>
        <button type="button" className="icon-close" aria-label={t("closeAccountDetails")} autoFocus
          onClick={() => details.current?.close()}><UiIcon name="close" /></button>
      </header>
      <dl>
        <div><dt>{t("accountName")}</dt><dd>{account.name}</dd></div>
        <div><dt>{t("accountType")}</dt><dd>{t("accountTypeLocal")}</dd></div>
        {account.id ? <div>
          <dt>{t("accountId")}</dt>
          <dd className="account-id-value">
            <code>{account.id}</code>
            <CopyButton text={account.id} label={t("copyAccountId")} icon feedbackMs={2500} />
          </dd>
        </div> : null}
      </dl>
    </dialog> : null}
  </div>;
}
