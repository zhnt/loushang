import { useTranslation } from "react-i18next";
import type { InteractionOutcome, PendingApproval } from "./client/model";

const outcomes = ["approve", "deny", "cancel"] as const;

export function ToolApproval({ approval, enabled, scope, onRespond }: {
  approval: PendingApproval;
  enabled: boolean;
  scope?: string;
  onRespond: (outcome: InteractionOutcome) => void;
}) {
  const { t } = useTranslation("session");
  const unavailable = !enabled || approval.status === "unavailable";
  return (
    <section className="tool-approval" aria-label={t("approval.title")} aria-busy={approval.status === "submitting"}>
      <strong>{t("approval.title")}</strong>
      {scope ? <p className="approval-scope">{t("approval.scope", { scope })}</p> : null}
      <pre>{approval.text}</pre>
      <div className="approval-actions">
        {outcomes.map((outcome) => (
          <button key={outcome} type="button" disabled={unavailable || approval.status !== "pending"}
            onClick={() => onRespond(outcome)}>{t(`approval.${outcome}`)}</button>
        ))}
        {approval.status === "processed" ? <span role="status">{t("approval.processed")}</span>
          : approval.status === "submitting" ? <span role="status">{t("approval.submitting")}</span>
          : unavailable ? <span role="status">{t("approval.unavailable")}</span> : null}
      </div>
    </section>
  );
}
