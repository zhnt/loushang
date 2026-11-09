import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { HostDetails } from "./client/trayHosts";
import "./TrayHostDialog.css";

export function TrayHostDialog({ details, error, onClose, onConfirm }: {
  details: HostDetails | null; error: string | null; onClose: () => void; onConfirm: () => void;
}) {
  const { t } = useTranslation(["workspace", "shell"]);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (details || error) { if (!dialog.current?.open) dialog.current?.showModal(); }
    else if (dialog.current?.open) dialog.current.close();
  }, [details, error]);
  const state = details?.probe.host;
  const name = details?.entry.kind === "local" ? t("shell:tray.localHost") : details?.entry.name;
  return <dialog ref={dialog} role={details?.confirm ? "alertdialog" : "dialog"} className="tray-host-dialog" aria-labelledby="tray-host-title" onClose={onClose}>
    <h2 id="tray-host-title">{details?.confirm ? t("localHost.confirmTitle") : t("localHost.identity")}{name ? ` · ${name}` : ""}</h2>
    {details?.confirm ? <p>{t("localHost.confirmStop")}</p> : null}
    {details ? <dl className="detail-list">
      <div><dt>{t("localHost.workspace")}</dt><dd>{details.probe.workspace}</dd></div>
      <div><dt>{t("shell:tray.service")}</dt><dd>{t(`shell:tray.${state?.state === "not_running" || state?.state === "exited" ? "stopped" : state?.state ?? "unknown"}`)}</dd></div>
      {state?.pid != null ? <div><dt>{t("localHost.pid")}</dt><dd>{state.pid}</dd></div> : null}
      {state?.instanceId ? <div><dt>{t("localHost.instanceId")}</dt><dd>{state.instanceId}</dd></div> : null}
      {state?.serviceInstanceId ? <div><dt>{t("localHost.serviceInstanceId")}</dt><dd>{state.serviceInstanceId}</dd></div> : null}
      {details.entry.webUrl ? <div><dt>{t("shell:tray.webAddress")}</dt><dd>{details.entry.webUrl}</dd></div> : null}
    </dl> : null}
    {error || state?.errorCode ? <p role="alert">{t("localHost.errors.unknown")} <code>{error ?? state?.errorCode}</code></p> : null}
    <footer>
      <button autoFocus onClick={onClose}>{details?.confirm ? t("localHost.cancel") : t("shell:close")}</button>
      {details?.confirm ? <button onClick={onConfirm}>{t("localHost.confirm")}</button> : null}
    </footer>
  </dialog>;
}
