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
  const restarting = details?.confirm === "restart";
  const state = details?.probe.host;
  const name = details?.entry.kind === "local" ? t("shell:tray.localHost") : details?.entry.name;
  return <dialog ref={dialog} role={details?.confirm ? "alertdialog" : "dialog"} className="tray-host-dialog" aria-labelledby="tray-host-title" onClose={onClose}>
    <h2 id="tray-host-title">{details?.confirm ? t(restarting ? "localHost.restartTitle" : "localHost.confirmTitle") : t("localHost.identity")}{name ? ` · ${name}` : ""}</h2>
    {details?.confirm ? <p>{t(restarting ? "localHost.confirmRestart" : "localHost.confirmStop")}</p> : null}
    {details ? <dl className="detail-list">
      <div><dt>{t("shell:tray.service")}</dt><dd>{state?.state === "exited" ? t("localHost.states.exited")
        : t(`shell:tray.${state?.state === "not_running" ? "stopped" : state?.state ?? "unknown"}`)}</dd></div>
      {state?.pid != null ? <div><dt>{t("localHost.pid")}</dt><dd><code>{state.pid}</code></dd></div> : null}
      {state?.instanceId ? <div><dt>{t("localHost.instanceId")}</dt><dd><code>{state.instanceId}</code></dd></div> : null}
      {state?.serviceInstanceId ? <div><dt>{t("localHost.serviceInstanceId")}</dt><dd><code>{state.serviceInstanceId}</code></dd></div> : null}
      {details.entry.webUrl ? <div><dt>{t("shell:tray.webAddress")}</dt><dd><code>{details.entry.webUrl}</code></dd></div> : null}
    </dl> : null}
    {error || state?.errorCode ? <p role="alert">{t("localHost.errors.unknown")} <code>{error ?? state?.errorCode}</code></p> : null}
    <footer>
      <button autoFocus onClick={onClose}>{details?.confirm ? t("localHost.cancel") : t("shell:close")}</button>
      {details?.confirm ? <button className="host-danger" onClick={onConfirm}>{t(restarting ? "localHost.restart" : "localHost.confirm")}</button> : null}
    </footer>
  </dialog>;
}
