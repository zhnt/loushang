import { useTranslation } from "react-i18next";
import type { InteractionOutcome, PendingApproval } from "./client/model";

const outcomes = ["approve", "deny", "cancel"] as const;

export function ToolApproval({ approval, enabled, onRespond }: {
  approval: PendingApproval;
  enabled: boolean;
  onRespond: (outcome: InteractionOutcome) => void;
}) {
  const { t } = useTranslation("session");
  const unavailable = !enabled || approval.status === "unavailable";
  return (
    <section className="tool-approval" aria-label={t("approval.title")} aria-busy={approval.status === "submitting"}>
      <strong>{t("approval.title")}</strong>
      <pre>{approval.text}</pre>
      <div className="approval-actions">
        {outcomes.map((outcome) => (
          <button key={outcome} type="button" disabled={unavailable || approval.status !== "pending"}
            onClick={() => onRespond(outcome)}>{t(`approval.${outcome}`)}</button>
        ))}
        {unavailable ? <span role="status">{t("approval.unavailable")}</span>
          : approval.status === "submitting" ? <span role="status">{t("approval.submitting")}</span> : null}
      </div>
    </section>
  );
}
