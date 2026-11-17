import { useState } from "react";
import { useTranslation } from "react-i18next";

export function CopyButton({ text, label }: { text: string; label?: string }) {
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
  return <span className="copy-action">
    <button type="button" className="secondary-button" aria-label={label}
      onClick={() => void copy()}>{t("clipboard.copy")}</button>
    {outcome ? <small role="status">{t(`clipboard.${outcome}`)}</small> : null}
  </span>;
}
