import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import App, { HarnessGui } from "./App";
import { useOfflineAccount } from "./client/offlineAccount";
import { nativeLiveAvailable } from "./client/nativeLiveClient";
import type { ConnectionState, HarnessClientUiPort } from "./client/model";
import { useSystemTray, type TrayConnection } from "./client/systemTray";
import { sharedSettings, webRequest } from "./client/hostApi";
import { createWebLiveClient } from "./client/webLiveClient";
import { useTrayHosts, selectTrayHost, type HostStatus, type HostAction as Action } from "./client/trayHosts";
import { TEMPORARY_WORKSPACE, type ProjectChat, type ProjectDirectory } from "./client/projectDirectory";
import { TrayHostDialog } from "./TrayHostDialog";
import "./LocalHostGate.css";

const emptyDirectory: ProjectDirectory = { projects: [], temporarySessions: [] };

const states = {
  unknown: "localHost.states.unknown", not_running: "localHost.states.notRunning",
  starting: "localHost.states.starting", running: "localHost.states.running",
  stopping: "localHost.states.stopping", exited: "localHost.states.exited",
} as const;
const errors = {
  authentication_failed: "localHost.errors.authentication",
  protocol_incompatible: "localHost.errors.protocol",
  connection_failed: "localHost.errors.connection",
  connection_unavailable: "localHost.errors.connection",
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
  const [directory, setDirectory] = useState(emptyDirectory);
  const [folderInput, setFolderInput] = useState(false);
  const [workspaceError, setWorkspaceError] = useState(false);
  const [workspacePending, setWorkspacePending] = useState(false);
  const [selection, setSelection] = useState<{ workspace: string; id: string } | null>(null);
  const workspaceEpoch = useRef(0);
  const workspaceClients = useRef(new Map<string, HarnessClientUiPort>());
  const workspaceMutation = useRef(false);
  const folderPicker = useRef(false);

  function openConversation(path: string, id?: string) {
    setWorkspace(path);
    setSelection(id ? { workspace: path, id } : null);
    let selected = workspaceClients.current.get(path);
    if (!selected) {
      selected = createWebLiveClient(path, connectionId.current);
      workspaceClients.current.set(path, selected);
    }
    clientRef.current = selected;
    setClient(selected);
    void webRequest({ operation: "remember-workspace", workspace: path }, connectionId.current).catch(() => {});
  }

  async function refreshDirectory() {
    const epoch = workspaceEpoch.current;
    const result = await webRequest<ProjectDirectory>({ operation: "workspace", action: "navigation" }, connectionId.current);
    if (epoch !== workspaceEpoch.current) return;
    setDirectory(result);
    return result;
  }

  async function changeDirectory(request: { action: "register" | "create-chat"; path?: string }) {
    if (workspaceMutation.current || pending.current || host.state !== "running" || host.errorCode) return false;
    workspaceMutation.current = true;
    setWorkspacePending(true);
    setWorkspaceError(false);
    const epoch = ++workspaceEpoch.current;
    try {
      const result = await webRequest<{ workspace: string; sessionId: string }>({ operation: "workspace", ...request }, connectionId.current);
      if (epoch !== workspaceEpoch.current) return false;
      if (request.action === "register") setFolderInput(false);
      else openConversation(result.workspace, result.sessionId);
      await refreshDirectory();
      return true;
    } catch {
      if (epoch === workspaceEpoch.current) setWorkspaceError(true);
      return false;
    } finally {
      workspaceMutation.current = false;
      setWorkspacePending(false);
    }
  }

  async function togglePin(chat: ProjectChat) {
    try {
      await webRequest({ operation: "preferences", scope: chat.scope, session: chat.id,
        action: chat.pinned ? "unpin" : "pin" }, connectionId.current);
      await refreshDirectory();
    } catch { setWorkspaceError(true); }
  }

  async function openFolder() {
    if (folderPicker.current || workspaceMutation.current || pending.current) return;
    if (!isTauri() || selectedId !== "local") {
      setFolderInput(true);
      return;
    }
    folderPicker.current = true;
    const epoch = workspaceEpoch.current;
    try {
      const path = await invoke<string | null>("pick_project_folder", {
        title: t("sidebar.addProject"), accept: t("sidebar.addProject"), cancel: t("localHost.cancel"),
      });
      if (path && epoch === workspaceEpoch.current) await changeDirectory({ action: "register", path });
    } catch {
      if (epoch === workspaceEpoch.current) setFolderInput(true);
    } finally {
      folderPicker.current = false;
    }
  }

  const [host, setHost] = useState<HostStatus>({ state: "unknown", errorCode: null });
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ action: "stop" | "restart"; workspace: string; instanceId?: string } | null>(null);
  const [client, setClient] = useState<HarnessClientUiPort | null>(null);
  const [connection, setConnection] = useState<ConnectionState | "connecting">("disconnected");
  const [selectedId, setSelectedId] = useState("");
  const [hostSettingsRequest, requestHostSettings] = useState(0);
  const [trayError, setTrayError] = useState<string | null>(null);
  const clientRef = useRef<HarnessClientUiPort | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const pendingAction = useRef<Action>("status");
  const connectionId = useRef<string | undefined>(undefined);

  async function perform(action: Action, preferred = workspace, expected: string | null | undefined = host.instanceId) {
    if ((pending.current && (action === "status" || pendingAction.current !== "status"))) return;
    const serial = ++generation.current;
    pending.current = true;
    pendingAction.current = action;
    setBusy(action !== "status");
    if (["connect", "start", "restart"].includes(action)) setConnection("connecting");
    if (action === "start" || action === "restart") setHost((current) => ({ ...current, state: "starting", errorCode: null }));
    if (action === "stop") setHost((current) => ({ ...current, state: "stopping", errorCode: null }));
    try {
      const request = { operation: "manage", action, ...(expected ? { instanceId: expected } : {}) };
      const result = await webRequest<HostStatus>(request, connectionId.current);
      if (serial !== generation.current) return;
      if (!(result.state in states)) throw new Error("management_response_invalid");
      setHost(result);
      if (result.state !== "running" || result.errorCode) setConnection("disconnected");
      if (["connect", "start", "restart"].includes(action) && result.state === "running" && !result.errorCode) {
        const directory = await refreshDirectory().catch(() => { setWorkspaceError(true); });
        if (serial !== generation.current || !directory) return;
        const available = preferred === TEMPORARY_WORKSPACE
          ? directory.temporarySessions.length > 0
          : directory.projects.some((project) => project.path === preferred && project.sessions.length > 0);
        if (available) openConversation(preferred);
        else setConnection("connected");
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
    const previous = { client: clientRef.current, id: connectionId.current, connection };
    ++generation.current;
    pending.current = true;
    pendingAction.current = "connect";
    setBusy(true);
    clientRef.current = null;
    workspaceEpoch.current++;

    setClient(null);
    setConnection("connecting");
    try {
      if (select) await selectTrayHost(id);
    } catch (error) {
      clientRef.current = previous.client;
      connectionId.current = previous.id;
      setClient(previous.client);
      setConnection(previous.connection);
      pending.current = false; setBusy(false);
      throw error;
    }
    if (id !== previous.id) {
      workspaceClients.current.clear();
      setDirectory(emptyDirectory);
      setSelection(null);
      setFolderInput(false);
      setWorkspaceError(false);
    }
    connectionId.current = id;
    setSelectedId(id);
    setHost({ state: "unknown", errorCode: null });
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
      const environment = await sharedSettings<{ supported: boolean; workspace: string; connectionId?: string }>({ operation: "environment" });
      if (!active || initialGeneration !== generation.current) return;
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
    if (host.state !== "running" || !supported) return;
    const timer = window.setInterval(() => { void perform("status"); }, 5000);
    return () => window.clearInterval(timer);
  });

  useEffect(() => {
    if (host.state !== "running" || host.errorCode || busy || workspacePending) return;
    const timer = window.setInterval(() => { void refreshDirectory().catch(() => {}); }, 3000);
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
  const reason = host.errorCode;
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
        <div className="local-host-actions">
          <button disabled={busy || !supported} onClick={() => void perform("status")}>{t("localHost.refresh")}</button>
          {host.state === "not_running" || (isTauri() && selectedId === "local" && host.state === "unknown" && !host.errorCode) ?
            <button disabled={busy || !supported} onClick={() => void perform("start", workspace.trim())}>{t("localHost.start")}</button> : null}
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
        <button autoFocus onClick={() => setConfirmation(null)}>{t("localHost.cancel")}</button>
        <button onClick={() => { const selected = confirmation; setConfirmation(null); void perform(selected.action, selected.workspace, selected.instanceId); }}>{t("localHost.confirm")}</button>
      </div>
    </div> : null}
  </>;
  return <><HarnessGui client={client} account={account} hostSettings={hostSettings}
    hostSettingsRequest={hostSettingsRequest} onConnectionChange={client ? setConnection : undefined}
    projectNavigation={{
      directory, available: host.state === "running" && !host.errorCode && !busy,
      pending: workspacePending, error: workspaceError, folderInput, selection,
      openFolder: () => { void openFolder(); },
      closeFolder: () => setFolderInput(false),
      register: (path) => changeDirectory({ action: "register", path }),
      create: (path) => { void changeDirectory({ action: "create-chat", ...(path ? { path } : {}) }); },
      togglePin: (chat) => { void togglePin(chat); },
      select: openConversation,
    }} />
    <TrayHostDialog details={trayHosts.details} error={trayHosts.error}
      onClose={() => { trayHosts.closeDetails(); trayHosts.clearError(); }} onConfirm={trayHosts.confirmStop} />
  </>;
}
