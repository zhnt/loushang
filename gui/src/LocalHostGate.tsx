import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import App, { HarnessGui } from "./App";
import { useOfflineAccount } from "./client/offlineAccount";
import { createNativeLiveClient, nativeLiveAvailable } from "./client/nativeLiveClient";
import type { ConnectionState, HarnessClientUiPort } from "./client/model";
import { useSystemTray, type TrayConnection } from "./client/systemTray";
import { sharedSettings, webRequest } from "./client/hostApi";
import { createWebLiveClient } from "./client/webLiveClient";
import { useTrayHosts, selectTrayHost, type HostStatus, type HostAction as Action } from "./client/trayHosts";
import { TrayHostDialog } from "./TrayHostDialog";
import "./LocalHostGate.css";

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

/** Shared Host management; conversations stay mounted during reconnect and selection. */
export default function LocalHostGate() {
  const { t, i18n } = useTranslation("workspace");
  const account = useOfflineAccount();
  const [legacy, setLegacy] = useState(false);
  const [supported, setSupported] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [host, setHost] = useState<HostStatus>({ state: "unknown", errorCode: null });
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ action: "stop" | "restart"; workspace: string; instanceId?: string } | null>(null);
  const [client, setClient] = useState<HarnessClientUiPort | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState | "connecting">("disconnected");
  const [selectedId, setSelectedId] = useState("");
  const [hostSettingsRequest, requestHostSettings] = useState(0);
  const [trayError, setTrayError] = useState<string | null>(null);
  const clientRef = useRef<HarnessClientUiPort | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const pendingAction = useRef<Action>("status");
  const remote = useRef(false);
  const connectionId = useRef<string | undefined>(undefined);

  async function perform(action: Action, path = workspace, expected: string | null | undefined = host.instanceId) {
    if (!path || (pending.current && (action === "status" || pendingAction.current !== "status"))) return;
    const serial = ++generation.current;
    pending.current = true;
    pendingAction.current = action;
    setBusy(action !== "status");
    if (["connect", "start", "restart"].includes(action)) setConnection("connecting");
    if (action === "start" || action === "restart") setHost((current) => ({ ...current, state: "starting", errorCode: null }));
    if (action === "stop") setHost((current) => ({ ...current, state: "stopping", errorCode: null }));
    try {
      const request = { action, workspace: path, ...(expected ? { instanceId: expected } : {}) };
      const result = isTauri() && !remote.current ? await invoke<HostStatus>("local_host_action", { request })
        : await webRequest<HostStatus>({ operation: "manage", ...request }, connectionId.current);
      if (serial !== generation.current) return;
      if (!(result.state in states)) throw new Error("management_response_invalid");
      setHost(result);
      if (result.state !== "running" || result.errorCode) setConnection("disconnected");
      if (result.workspace) {
        setWorkspace(result.workspace);
        if (result.state === "running" && !result.errorCode) {
          if (remote.current) await webRequest({ operation: "remember-workspace", workspace: result.workspace }, connectionId.current);
          else await sharedSettings({ operation: "remember-workspace", workspace: result.workspace });
        }
      }
      if (serial !== generation.current) return;
      if (["connect", "start", "restart"].includes(action) && result.state === "running" && !result.errorCode) {
        setConnectionError(null);
        clientRef.current ??= isTauri() && !remote.current ? createNativeLiveClient() : createWebLiveClient(path, connectionId.current);
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

  async function activateHost(id: string, select = true) {
    if (pending.current && pendingAction.current !== "status") throw new Error("management_busy");
    const previous = { client: clientRef.current, id: connectionId.current, remote: remote.current, connection };
    ++generation.current;
    pending.current = true;
    pendingAction.current = "connect";
    setBusy(true);
    clientRef.current = null;
    setClient(null);
    setConnection("connecting");
    try {
      if (select) await selectTrayHost(id);
    } catch (error) {
      clientRef.current = previous.client;
      connectionId.current = previous.id;
      remote.current = previous.remote;
      setClient(previous.client);
      setConnection(previous.connection);
      pending.current = false; setBusy(false);
      throw error;
    }
    connectionId.current = id;
    remote.current = true;
    setSelectedId(id);
    setHost({ state: "unknown", errorCode: null });
    setConnectionError(null);
    try {
      const environment = await webRequest<{ supported: boolean; workspace: string }>({ operation: "environment" }, id);
      setWorkspace(environment.workspace);
      setSupported(environment.supported);
      pending.current = false;
      if (environment.supported) await perform("connect", environment.workspace, null);
      else setConnection("disconnected");
    } catch (error) {
      setHost({ state: "unknown", errorCode: "connection_failed" });
      setConnection("disconnected");
      throw error;
    } finally { pending.current = false; setBusy(false); }
  }

  useEffect(() => {
    let active = true;
    const initialGeneration = generation.current;
    void (async () => {
      if (await nativeLiveAvailable()) { if (active) setLegacy(true); return; }
      const environment = await sharedSettings<{ supported: boolean; workspace: string; remote?: boolean; connectionId?: string }>({ operation: "environment" });
      if (!active || initialGeneration !== generation.current) return;
      remote.current = environment.remote ?? !isTauri();
      connectionId.current = environment.connectionId;
      setSelectedId(environment.connectionId ?? "local");
      setSupported(environment.supported);
      const selected = environment.workspace;
      setWorkspace(selected);
      if (environment.supported) await perform("connect", selected, undefined);
    })().catch(() => { if (active && initialGeneration === generation.current) setHost({ state: "unknown", errorCode: "management_unavailable" }); });
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

  const trayConnection: TrayConnection = busy && ["connect", "start", "restart"].includes(pendingAction.current) ? "connecting"
    : connection === "connected" ? "connected"
    : connection === "connecting" || connection === "resync-required" ? "connecting" : "disconnected";
  const trayHosts = useTrayHosts({
    enabled: !legacy, selectedId, localName: i18n.t("shell:tray.localHost"),
    workspace, host, supported: supported === true, busy, connection: trayConnection,
    onSelect: (id) => activateHost(id),
    onManage: (action, path, instanceId) => action === "connect" && connectionId.current
      ? activateHost(connectionId.current, false) : perform(action, path, instanceId),
  });
  useSystemTray({ userName: account?.name ?? "", language: i18n.resolvedLanguage ?? "en-US", hosts: trayHosts.hosts },
    trayHosts.action, (error) => { setTrayError(error); requestHostSettings((value) => value + 1); });

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
  return <><HarnessGui client={client} account={account} hostSettings={hostSettings}
    hostSettingsRequest={hostSettingsRequest} onConnectionChange={setConnection} />
    <TrayHostDialog details={trayHosts.details} error={trayHosts.error}
      onClose={() => { trayHosts.closeDetails(); trayHosts.clearError(); }} onConfirm={trayHosts.confirmStop} />
  </>;
}
