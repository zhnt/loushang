import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";

export function CopyButton({ text, label, icon = false, showLabel = false, feedbackMs }: {
  readonly text: string;
  readonly label?: string;
  readonly icon?: boolean;
  readonly showLabel?: boolean;
  readonly feedbackMs?: number;
}) {
  const { t } = useTranslation("common");
  const [feedback, setFeedback] = useState<{ outcome: "copied" | "failed" }>();
  const outcome = feedback?.outcome;
  useEffect(() => {
    if (!feedback || feedbackMs === undefined) return;
    const timer = window.setTimeout(() => setFeedback(undefined), feedbackMs);
    return () => window.clearTimeout(timer);
  }, [feedback, feedbackMs]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setFeedback({ outcome: "copied" });
    } catch {
      setFeedback({ outcome: "failed" });
    }
  }
  if (icon) return <span className="panel-copy" data-outcome={outcome}>
    <button type="button" className="panel-icon-button" aria-label={label ?? t("clipboard.copy")}
      data-tooltip={outcome ? t(`clipboard.${outcome}`) : label ?? t("clipboard.copy")} onClick={() => void copy()}>
      <UiIcon name={feedbackMs === undefined || !outcome ? "copy" : outcome === "copied" ? "check" : "close"} />
    </button>
    <span className="sr-only" role="status">{outcome ? t(`clipboard.${outcome}`) : ""}</span>
  </span>;
  return <span className="copy-action">
    <button type="button" className="secondary-button" aria-label={label}
      onClick={() => void copy()}>{(showLabel && label) || t("clipboard.copy")}</button>
    {outcome ? <small role="status">{t(`clipboard.${outcome}`)}</small> : null}
  </span>;
}
