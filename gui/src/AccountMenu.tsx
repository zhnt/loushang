import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";

export function AccountMenu({ compact = false, status, detail, onSettings }: {
  compact?: boolean;
  status: string;
  detail?: string;
  onSettings: () => void;
}) {
  const { t } = useTranslation("shell");
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const settings = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    settings.current?.focus();
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
    trigger.current?.focus();
  }

  return <div ref={root} className={compact ? "account-menu account-menu-compact" : "account-menu"}
    onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
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
      title={compact ? t("accountMenu") : detail} onClick={() => setOpen(!open)}>
      {/* i18next-instrument-ignore-next-line: fixture avatar initial */}
      <span className="user-avatar" aria-hidden="true">Z</span>
      {compact ? null : <>
        {/* i18next-instrument-ignore-next-line: existing account label */}
        <span className="account-label"><strong>zhnt</strong><small>{status}</small></span>
        <span aria-hidden="true">⋯</span>
      </>}
    </button>
    {open ? <div id={id} className="account-popover">
      <div className="account-popover-status">{status}</div>
      <button ref={settings} type="button" onClick={() => { dismiss(); onSettings(); }}>
        <UiIcon name="settings" />
        {t("settings")}
      </button>
    </div> : null}
  </div>;
}
