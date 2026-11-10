import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { HostDetails } from "./client/trayHosts";
import { availableTrayAction, type TrayAction, type TrayHost } from "./client/systemTray";
import "./TrayHostDialog.css";

export function TrayHostDialog({ details, host, error, onAction, onClose, onConfirm }: {
  details: HostDetails | null; error: string | null; onClose: () => void; onConfirm: () => void;
  host?: TrayHost; onAction: (id: string, action: TrayAction) => void;
}) {
  const { t } = useTranslation(["workspace", "shell"]);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (details || error) { if (!dialog.current?.open) dialog.current?.showModal(); }
    else if (dialog.current?.open) dialog.current.close();
  }, [details, error]);
  const state = details?.probe.host;
  const name = details?.entry.kind === "local" ? t("shell:tray.localHost") : details?.entry.name;
  return <dialog ref={dialog} role={details?.confirm ? "alertdialog" : "dialog"} className="tray-host-dialog" aria-labelledby="tray-host-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <h2 id="tray-host-title">{details?.confirm ? t("localHost.confirmTitle") : t("localHost.identity")}{name ? ` · ${name}` : ""}</h2>
    {details?.confirm ? <p>{t("localHost.confirmStop")}</p> : null}
    {details ? <dl className="detail-list">
      <div><dt>{t("localHost.workspace")}</dt><dd>{details.probe.workspace}</dd></div>
      <div><dt>{t("shell:tray.service")}</dt><dd>{state?.state === "exited" ? t("localHost.states.exited")
        : t(`shell:tray.${state?.state === "not_running" ? "stopped" : state?.state ?? "unknown"}`)}</dd></div>
      {state?.pid != null ? <div><dt>{t("localHost.pid")}</dt><dd>{state.pid}</dd></div> : null}
      {state?.instanceId ? <div><dt>{t("localHost.instanceId")}</dt><dd>{state.instanceId}</dd></div> : null}
      {state?.serviceInstanceId ? <div><dt>{t("localHost.serviceInstanceId")}</dt><dd>{state.serviceInstanceId}</dd></div> : null}
      {details.entry.webUrl ? <div><dt>{t("shell:tray.webAddress")}</dt><dd>{details.entry.webUrl}</dd></div> : null}
    </dl> : null}
    {error || state?.errorCode ? <p role="alert">{t("localHost.errors.unknown")} <code>{error ?? state?.errorCode}</code></p> : null}
    {host && details && !details.confirm ? <div className="tray-host-actions">
      <button disabled={!availableTrayAction(host, "enable")} onClick={() => onAction(host.id, "enable")}>{t("shell:tray.enableLabel")}</button>
      <button disabled={!availableTrayAction(host, "reconnect")} onClick={() => onAction(host.id, "reconnect")}>{t("shell:tray.reconnectLabel")}</button>
      {host.service !== "running" ? <button disabled={!availableTrayAction(host, "start")} onClick={() => onAction(host.id, "start")}>
        {t("shell:tray.startLabel")}{host.configureStart ? "…" : ""}
      </button> : null}
      {host.service === "running" ? <button disabled={!availableTrayAction(host, "stop")} onClick={() => onAction(host.id, "stop")}>{t("shell:tray.stopLabel")}</button> : null}
    </div> : null}
    <footer>
      <button autoFocus onClick={onClose}>{details?.confirm ? t("localHost.cancel") : t("shell:close")}</button>
      {details?.confirm ? <button onClick={onConfirm}>{t("localHost.confirm")}</button> : null}
    </footer>
  </dialog>;
}
