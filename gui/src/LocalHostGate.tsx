import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import App, { HarnessGui } from "./App";
import { useOfflineAccount } from "./client/offlineAccount";
import { createNativeLiveClient, nativeLiveAvailable } from "./client/nativeLiveClient";
import type { ConnectionState, HarnessClientUiPort } from "./client/model";
import { useSystemTray, type TrayConnection } from "./client/systemTray";
import "./LocalHostGate.css";

type HostState = "unknown" | "not_running" | "starting" | "running" | "stopping" | "exited";
type Action = "status" | "start" | "connect" | "stop" | "restart";
interface HostStatus {
  state: HostState;
  errorCode: string | null;
  workspace?: string;
  instanceId?: string;
  serviceInstanceId?: string;
  pid?: number;
}
const WORKSPACE_KEY = "loushang.gui.local-workspace.v1";
const states = {
  unknown: "localHost.states.unknown", not_running: "localHost.states.notRunning",
  starting: "localHost.states.starting", running: "localHost.states.running",
  stopping: "localHost.states.stopping", exited: "localHost.states.exited",
} as const;
const errors = {
  authentication_failed: "localHost.errors.authentication",
  protocol_incompatible: "localHost.errors.protocol",
  connection_failed: "localHost.errors.connection",
  client_disconnected: "localHost.errors.disconnected",
  attachment_unavailable: "localHost.errors.attachment",
  management_unavailable: "localHost.errors.unavailable",
  record_invalid: "localHost.errors.record",
  local_record_corrupt: "localHost.errors.record",
  instance_changed: "localHost.errors.instance",
} as const;

/** Management remains native. The conversation stays mounted during reconnect. */
export default function LocalHostGate() {
  const { t, i18n } = useTranslation("workspace");
  const account = useOfflineAccount();
  const [legacy, setLegacy] = useState(!isTauri());
  const [supported, setSupported] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [host, setHost] = useState<HostStatus>({ state: "unknown", errorCode: null });
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ action: "stop" | "restart"; workspace: string; instanceId?: string } | null>(null);
  const [client, setClient] = useState<HarnessClientUiPort | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState | "connecting">("disconnected");
  const [webUrl, setWebUrl] = useState<string | undefined>();
  const [hostSettingsRequest, requestHostSettings] = useState(0);
  const [trayError, setTrayError] = useState<string | null>(null);
  const clientRef = useRef<HarnessClientUiPort | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);

  async function perform(action: Action, path = workspace, expected = host.instanceId) {
    if (pending.current || !path) return;
    const serial = ++generation.current;
    pending.current = true;
    setBusy(true);
    if (["connect", "start", "restart"].includes(action)) setConnection("connecting");
    if (action === "start" || action === "restart") setHost((current) => ({ ...current, state: "starting", errorCode: null }));
    if (action === "stop") setHost((current) => ({ ...current, state: "stopping", errorCode: null }));
    try {
      const result = await invoke<HostStatus>("local_host_action", {
        request: { action, workspace: path, ...(expected ? { instanceId: expected } : {}) },
      });
      if (serial !== generation.current) return;
      if (!(result.state in states)) throw new Error("management_response_invalid");
      setHost(result);
      if (result.state !== "running" || result.errorCode) setConnection("disconnected");
      if (result.workspace) {
        setWorkspace(result.workspace);
        try { localStorage.setItem(WORKSPACE_KEY, result.workspace); } catch { /* Optional UI preference. */ }
      }
      if (["connect", "start", "restart"].includes(action) && result.state === "running" && !result.errorCode) {
        setConnectionError(null);
        clientRef.current ??= createNativeLiveClient();
        setClient(clientRef.current);
      }
    } catch (error) {
      if (serial === generation.current) {
        setHost({ state: "unknown", errorCode: typeof error === "string" ? error : "management_unconfirmed" });
        setConnection("disconnected");
      }
    } finally {
      if (serial === generation.current) { pending.current = false; setBusy(false); }
    }
  }

  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    void (async () => {
      if (await nativeLiveAvailable()) { if (active) setLegacy(true); return; }
      const environment = await invoke<{ supported: boolean; workspace: string; webUrl?: string }>("local_host_environment");
      if (!active) return;
      setSupported(environment.supported);
      setWebUrl(environment.webUrl);
      let selected = environment.workspace;
      try { selected = localStorage.getItem(WORKSPACE_KEY) ?? selected; } catch { /* Optional preference. */ }
      setWorkspace(selected);
      if (environment.supported) await perform("connect", selected, undefined);
    })().catch(() => { if (active) setHost({ state: "unknown", errorCode: "management_unavailable" }); });
    return () => { active = false; };
    // Native setup is process-local; workspace edits are explicit selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!isTauri() || legacy) return;
    let active = true;
    const release = listen<{ state: string; reason?: string }>("gui://live-connection-state", ({ payload }) => {
      if (active && payload.state === "disconnected") setConnectionError(payload.reason ?? "client_disconnected");
    });
    const initial = listen("gui://live-initial-snapshot", () => { if (active) setConnectionError(null); });
    return () => { active = false; void release.then((stop) => stop()); void initial.then((stop) => stop()); };
  }, [legacy]);

  useEffect(() => {
    if (!client || !supported) return;
    const timer = window.setInterval(() => { void perform("status"); }, 5000);
    return () => window.clearInterval(timer);
  });

  const trayConnection: TrayConnection = connection === "connected" ? "connected"
    : connection === "connecting" || connection === "resync-required" ? "connecting" : "disconnected";
  useSystemTray({
    userName: account?.name ?? "", language: i18n.resolvedLanguage ?? "en-US",
    hosts: !legacy && workspace ? [{
      id: workspace, name: i18n.t("shell:tray.localHost"), selected: true,
      connection: trayConnection, service: host.state === "not_running" || host.state === "exited" ? "stopped" : host.state,
      busy, manageable: supported === true, webUrl,
    }] : [],
  }, (_id, action) => {
    if (action === "info" || action === "stop") requestHostSettings((value) => value + 1);
    if (action === "stop") setConfirmation({ action: "stop", workspace, instanceId: host.instanceId });
    else if (action !== "info") void perform(action === "start" ? "start" : "connect");
  }, (error) => { setTrayError(error); requestHostSettings((value) => value + 1); });

  if (legacy) return <App account={account} />;
  const reason = host.errorCode ?? (host.state === "running" ? connectionError : null);
  const errorLabel = reason && reason in errors ? t(errors[reason as keyof typeof errors])
    : reason?.startsWith("start_") || reason === "spawn_failed" ? t("localHost.errors.start")
    : reason?.startsWith("stop_") || reason === "cleanup_incomplete" ? t("localHost.errors.stop")
    : t("localHost.errors.unknown");
  const stop = (action: "stop" | "restart") => {
    setConfirmation({ action, workspace, instanceId: host.instanceId });
  };
  const hostSettings = <>
    <section className="local-host-panel" aria-labelledby="settings-local-host">
      <div className="local-host-heading">
        <h3 id="settings-local-host">{t("localHost.title")}</h3>
        <span className="local-host-status" data-state={host.state} role="status">
          {supported === false ? t("localHost.unsupported") : t(states[host.state])}
        </span>
      </div>
      <div className="local-host-card">
        <label>{t("localHost.workspace")}
          <input value={workspace} disabled={!!client || busy} onChange={(event) => {
            setWorkspace(event.target.value);
            setHost({ state: "unknown", errorCode: null });
            setConnection("disconnected");
          }} placeholder={t("localHost.pathHint")} />
        </label>
        <div className="local-host-actions">
          <button disabled={busy || !supported || !workspace} onClick={() => void perform("status")}>{t("localHost.refresh")}</button>
          {host.state === "not_running" ? <button disabled={busy || !supported} onClick={() => void perform("start")}>{t("localHost.start")}</button> : null}
          {host.state === "running" ? <>
            <button disabled={busy} onClick={() => void perform("connect")}>{t(client ? "localHost.reconnect" : "localHost.connect")}</button>
            <button disabled={busy} onClick={() => stop("stop")}>{t("localHost.stop")}</button>
            <button disabled={busy} onClick={() => stop("restart")}>{t("localHost.restart")}</button>
          </> : null}
        </div>
      </div>
      {reason ? <p role="alert">{errorLabel} <code>{reason}</code></p> : null}
      {trayError ? <p role="alert">{i18n.t("shell:tray.webError")}</p> : null}
      <section className="local-host-card local-host-info" aria-labelledby="local-host-info-title">
        <h4 id="local-host-info-title">{t("localHost.identity")}</h4>
        {host.instanceId || host.serviceInstanceId || host.pid != null ? <dl className="detail-list">
          {host.pid != null ? <div><dt>{t("localHost.pid")}</dt><dd>{host.pid}</dd></div> : null}
          {host.instanceId ? <div><dt>{t("localHost.instanceId")}</dt><dd>{host.instanceId}</dd></div> : null}
          {host.serviceInstanceId ? <div><dt>{t("localHost.serviceInstanceId")}</dt><dd>{host.serviceInstanceId}</dd></div> : null}
        </dl> : <p>{t("localHost.identityUnavailable")}</p>}
      </section>
    </section>
    {confirmation ? <div className="local-host-confirm" role="alertdialog" aria-modal="true" aria-label={t("localHost.confirmTitle")} onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setConfirmation(null); } }}>
      <div><strong>{t("localHost.confirmTitle")}</strong><p>{t("localHost.confirmStop")}</p>
        <p>{confirmation.workspace}</p>
        <button autoFocus onClick={() => setConfirmation(null)}>{t("localHost.cancel")}</button>
        <button onClick={() => { const selected = confirmation; setConfirmation(null); void perform(selected.action, selected.workspace, selected.instanceId); }}>{t("localHost.confirm")}</button>
      </div>
    </div> : null}
  </>;
  return <HarnessGui client={client} account={account} hostSettings={hostSettings}
    hostSettingsRequest={hostSettingsRequest} onConnectionChange={setConnection} />;
}
