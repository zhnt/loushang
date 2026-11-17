import { useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";

export function CopyButton({ text, label, icon = false }: { text: string; label?: string; icon?: boolean }) {
  const { t } = useTranslation("common");
  const [outcome, setOutcome] = useState<"copied" | "failed">();
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setOutcome("copied");
    } catch {
      setOutcome("failed");
    }
  }
  if (icon) return <span className="panel-copy" data-outcome={outcome}>
    <button type="button" className="panel-icon-button" aria-label={label ?? t("clipboard.copy")}
      title={outcome ? t(`clipboard.${outcome}`) : label ?? t("clipboard.copy")} onClick={() => void copy()}>
      <UiIcon name="copy" />
    </button>
    <span className="sr-only" role="status">{outcome ? t(`clipboard.${outcome}`) : ""}</span>
  </span>;
  return <span className="copy-action">
    <button type="button" className="secondary-button" aria-label={label}
      onClick={() => void copy()}>{t("clipboard.copy")}</button>
    {outcome ? <small role="status">{t(`clipboard.${outcome}`)}</small> : null}
  </span>;
}
