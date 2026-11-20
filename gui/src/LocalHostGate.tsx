import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import App, { HarnessGui } from "./App";
import { useOfflineAccount } from "./client/offlineAccount";
import { nativeLiveAvailable, validateSessionModels } from "./client/nativeLiveClient";
import type { ConnectionState, HarnessClientUiPort } from "./client/model";
import { useSystemTray, type TrayConnection } from "./client/systemTray";
import { sharedSettings, webRequest } from "./client/hostApi";
import { createWebLiveClient, type WebLiveClient } from "./client/webLiveClient";
import { useTrayHosts, selectTrayHost, type HostStatus, type HostAction as Action } from "./client/trayHosts";
import { projectKey, TEMPORARY_WORKSPACE, workspaceName, type ManagedProjectNavigation, type ProjectChat, type ProjectDirectory } from "./client/projectDirectory";
import { TrayHostDialog } from "./TrayHostDialog";
import "./LocalHostGate.css";

const emptyDirectory: ProjectDirectory = { projects: [], temporarySessions: [] };
const openLocalWorkspacePath: NonNullable<ManagedProjectNavigation["openProjectPath"]> = (workspace, fingerprint, file) =>
  webRequest({ operation: "open-project-path", workspace, fingerprint, ...(file ? { file } : {}) }, "local");

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
  const [route, setRoute] = useState<"detecting" | "native" | "web">("detecting");
  const [supported, setSupported] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [directory, setDirectory] = useState(emptyDirectory);
  const [folderInput, setFolderInput] = useState(false);
  const [workspaceError, setWorkspaceError] = useState(false);
  const [workspacePending, setWorkspacePending] = useState(false);
  const [selection, setSelection] = useState<ManagedProjectNavigation["selection"]>(null);
  const workspaceEpoch = useRef(0);
  const workspaceClients = useRef(new Map<string, WebLiveClient>());
  const workspaceMutation = useRef(false);
  const folderPicker = useRef(false);

  function workspaceClient(path: string) {
    let selected = workspaceClients.current.get(path);
    if (!selected) {
      selected = createWebLiveClient(path, connectionId.current);
      workspaceClients.current.set(path, selected);
    }
    return selected;
  }

  function openConversation(path: string, id?: string) {
    setWorkspace(path);
    setSelection({ workspace: path, id });
    const selected = workspaceClient(path);
    clientRef.current = selected;
    setClient(selected);
    void webRequest({ operation: "remember-workspace", workspace: path }, connectionId.current).catch(() => {});
  }

  async function refreshDirectory() {
    const epoch = workspaceEpoch.current;
    const result = await webRequest<ProjectDirectory>({ operation: "workspace", action: "navigation" }, connectionId.current);
    if (epoch !== workspaceEpoch.current) return;
    setDirectory(result);
    setWorkspaceError(false);
    return result;
  }

  async function registerWorkspace(path: string) {
    if (workspaceMutation.current || pending.current || host.state !== "running" || host.errorCode) return false;
    workspaceMutation.current = true;
    setWorkspacePending(true);
    setWorkspaceError(false);
    const epoch = ++workspaceEpoch.current;
    try {
      await webRequest({
        operation: "workspace", action: "create-workspace", name: workspaceName(path), path, alias: "main",
      }, connectionId.current);
      if (epoch !== workspaceEpoch.current) return false;
      setFolderInput(false);
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

  const editWorkspace: NonNullable<ManagedProjectNavigation["editWorkspace"]> = async (edit) => {
    if (workspaceMutation.current || pending.current || host.state !== "running" || host.errorCode) {
      throw new Error("operation_unavailable");
    }
    workspaceMutation.current = true;
    setWorkspacePending(true);
    const epoch = ++workspaceEpoch.current;
    const origin = connectionId.current;
    const deleting = edit.action === "delete-workspace-with-history";
    let resume: (() => void) | undefined;
    try {
      if (deleting) resume = await workspaceClients.current.get(edit.workspaceId)?.suspend();
      if (epoch !== workspaceEpoch.current) return;
      await webRequest({ operation: "workspace", ...edit }, origin);
      if (epoch !== workspaceEpoch.current) return;
      if (!deleting) {
        await refreshDirectory();
        return;
      }
      const id = edit.workspaceId;
      ++workspaceEpoch.current;
      const deletedClient = workspaceClients.current.get(id);
      workspaceClients.current.delete(id);
      if (deletedClient && clientRef.current === deletedClient) {
        clientRef.current = null;
        setClient(null);
        setWorkspace("");
      }
      setSelection((current) => current?.workspace === id ? null : current);
      setDirectory((current) => ({
        ...current, projects: current.projects.filter((project) => projectKey(project) !== id),
      }));
    } finally {
      resume?.();
      workspaceMutation.current = false;
      setWorkspacePending(false);
      if (deleting && origin === connectionId.current) {
        void refreshDirectory().catch(() => { if (origin === connectionId.current) setWorkspaceError(true); });
      }
    }
  };

  const createChat: ManagedProjectNavigation["createChat"] = async (path, continuityId, title) => {
    const origin = connectionId.current;
    const destination = path ?? TEMPORARY_WORKSPACE;
    const previous = workspaceClients.current.get(destination);
    const bound = workspaceClient(destination);
    let sessionId: string | undefined;
    // Creation acquires the Mux controller. Release just the view it will use.
    const resume = await previous?.suspend();
    try {
      if (origin !== connectionId.current) return null;
      const result = await webRequest<{ accepted: false } | { workspace: string; sessionId: string }>({
        operation: "workspace", action: "create-chat", path, continuityId, title,
      }, origin);
      if ("accepted" in result && result.accepted === false) return null;
      if ("sessionId" in result && typeof result.sessionId === "string" && result.workspace === destination) {
        sessionId = result.sessionId;
      }
    } catch {
      // Only a matching continuation in the target Mux proves an unknown create.
    } finally {
      resume?.();
    }
    return {
      client: bound,
      sessionId,
      show(id) {
        if (origin !== connectionId.current) return false;
        workspaceClients.current.set(destination, bound);
        openConversation(destination, id);
        return true;
      },
    };
  };

  async function deleteChat(path: string, chat: ProjectChat) {
    const serviceInstanceId = host.serviceInstanceId;
    if (!serviceInstanceId || workspaceMutation.current || pending.current || host.state !== "running" || host.errorCode) return false;
    workspaceMutation.current = true;
    setWorkspacePending(true);
    const epoch = ++workspaceEpoch.current;
    const origin = connectionId.current;
    let resume: (() => void) | undefined;
    try {
      resume = await workspaceClients.current.get(path)?.suspend();
      if (epoch !== workspaceEpoch.current) return false;
      const { accepted } = await webRequest<{ accepted: boolean }>({
        operation: "workspace", action: "delete-chat", path, sessionId: chat.id, scope: chat.scope, serviceInstanceId,
      }, origin);
      if (accepted !== true || epoch !== workspaceEpoch.current) return false;
      const withoutChat = (chats: readonly ProjectChat[]) =>
        chats.filter((item) => item.id !== chat.id || item.scope !== chat.scope);
      ++workspaceEpoch.current;
      setDirectory((current) => ({
        projects: current.projects.map((project) => projectKey(project) === path
          ? { ...project, sessions: withoutChat(project.sessions) } : project),
        temporarySessions: path === TEMPORARY_WORKSPACE ? withoutChat(current.temporarySessions) : current.temporarySessions,
      }));
      setSelection((current) => current?.workspace === path && current.id === chat.id ? { workspace: path } : current);
      return true;
    } catch {
      return false;
    } finally {
      resume?.();
      workspaceMutation.current = false;
      setWorkspacePending(false);
      if (origin === connectionId.current) void refreshDirectory().catch(() => {});
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
    setWorkspaceError(false);
    const epoch = workspaceEpoch.current;
    try {
      const path = await invoke<string | null>("pick_project_folder", {
        title: t("sidebar.addProject"), accept: t("sidebar.addProject"), cancel: t("localHost.cancel"),
      });
      if (path && epoch === workspaceEpoch.current) await registerWorkspace(path);
    } catch {
      if (epoch === workspaceEpoch.current) setWorkspaceError(true);
    } finally {
      folderPicker.current = false;
    }
  }

  const [host, setHost] = useState<HostStatus>({ state: "unknown", errorCode: null });
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ action: "stop" | "restart"; instanceId?: string } | null>(null);
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

  async function perform(action: Action, expected: string | null | undefined = host.instanceId, restoreSelection = selection) {
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
        if (serial !== generation.current) return;
        const path = restoreSelection?.workspace;
        const chats = path === TEMPORARY_WORKSPACE ? directory?.temporarySessions
          : directory?.projects.find((project) => projectKey(project) === path)?.sessions;
        if (restoreSelection?.id && chats?.some((chat) => chat.id === restoreSelection.id)) {
          openConversation(restoreSelection.workspace, restoreSelection.id);
        } else setConnection("connected");
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
      if (environment.supported) await perform("connect", null, id === previous.id ? selection : null);
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
      const native = await nativeLiveAvailable();
      if (!active) return;
      setRoute(native ? "native" : "web");
      if (native) return;
      const environment = await sharedSettings<{ supported: boolean; workspace: string; connectionId?: string }>({ operation: "environment" });
      if (!active || initialGeneration !== generation.current) return;
      connectionId.current = environment.connectionId;
      setSelectedId(environment.connectionId ?? "local");
      setSupported(environment.supported);
      setWorkspace(environment.workspace);
      if (environment.supported) await perform("connect", null, null);
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
    : connection === "connecting" ? "connecting" : "disconnected";
  const trayHosts = useTrayHosts({
    enabled: route === "web", selectedId, localName: i18n.t("shell:tray.localHost"),
    workspace, host, supported: supported === true, busy, connection: trayConnection,
    onSelect: (id) => activateHost(id),
    onManage: (action, _path, instanceId) => action === "connect" && connectionId.current
      ? activateHost(connectionId.current, false) : perform(action, instanceId),
  });
  useSystemTray({ userName: account?.name ?? "", language: i18n.resolvedLanguage ?? "en-US", hosts: trayHosts.hosts },
    trayHosts.action, (error) => { setTrayError(error); requestHostSettings((value) => value + 1); });

  if (route === "native") return <App account={account} />;
  const reason = host.errorCode;
  const errorLabel = reason && reason in errors ? t(errors[reason as keyof typeof errors])
    : reason?.startsWith("start_") || reason === "spawn_failed" ? t("localHost.errors.start")
    : reason?.startsWith("stop_") || reason === "cleanup_incomplete" ? t("localHost.errors.stop")
    : t("localHost.errors.unknown");
  const canStart = host.manageable && ["not_running", "exited"].includes(host.state);
  const startHost = () => void perform("start");
  const stop = (action: "stop" | "restart") => {
    setConfirmation({ action, instanceId: host.instanceId });
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
          {canStart ?
            <button disabled={busy} onClick={startHost}>{t("localHost.start")}</button> : null}
          {host.state === "running" ? <>
            <button disabled={busy} onClick={() => void perform("connect")}>{t(client ? "localHost.reconnect" : "localHost.connect")}</button>
            {host.manageable && host.instanceId && <><button className="host-danger" disabled={busy} onClick={() => stop("stop")}>{t("localHost.stop")}</button>
            <button className="host-danger" disabled={busy} onClick={() => stop("restart")}>{t("localHost.restart")}</button></>}
          </> : null}
        </div>
      </div>
      {reason ? <p role="alert">{errorLabel} <code>{reason}</code></p> : null}
      {trayError ? <p role="alert">{i18n.t("shell:tray.webError")}</p> : null}
      <section className="local-host-card local-host-info" aria-labelledby="local-host-info-title">
        <h4 id="local-host-info-title">{t("localHost.identity")}</h4>
        {host.instanceId || host.serviceInstanceId || host.pid != null ? <dl className="detail-list">
          {host.pid != null ? <div><dt>{t("localHost.pid")}</dt><dd><code>{host.pid}</code></dd></div> : null}
          {host.instanceId ? <div><dt>{t("localHost.instanceId")}</dt><dd><code>{host.instanceId}</code></dd></div> : null}
          {host.serviceInstanceId ? <div><dt>{t("localHost.serviceInstanceId")}</dt><dd><code>{host.serviceInstanceId}</code></dd></div> : null}
        </dl> : <p>{t("localHost.identityUnavailable")}</p>}
      </section>
    </section>
    {confirmation ? <div className="local-host-confirm" role="alertdialog" aria-modal="true"
      aria-labelledby="host-confirm-title" aria-describedby="host-confirm-impact"
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setConfirmation(null); } }}>
      <div>
        <strong id="host-confirm-title">{t(confirmation.action === "restart" ? "localHost.restartTitle" : "localHost.confirmTitle")}</strong>
        <p id="host-confirm-impact">{t(confirmation.action === "restart" ? "localHost.confirmRestart" : "localHost.confirmStop")}</p>
        <button autoFocus onClick={() => setConfirmation(null)}>{t("localHost.cancel")}</button>
        <button className="host-danger" onClick={() => {
          const selected = confirmation;
          setConfirmation(null);
          void perform(selected.action, selected.instanceId);
        }}>{t(confirmation.action === "restart" ? "localHost.restart" : "localHost.confirm")}</button>
      </div>
    </div> : null}
  </>;
  const requestConnection = connectionId.current;
  return <><HarnessGui client={client} account={account} hostSettings={hostSettings}
    startLocalHost={canStart ? <button type="button" className="primary-button" disabled={busy} onClick={startHost}>{t("localHost.start")}</button> : null}
    hostSettingsRequest={hostSettingsRequest} onConnectionChange={client ? setConnection : undefined}
    managedHostConnection={busy ? { status: pendingAction.current === "stop" ? "disconnected" : "connecting" }
      : supported === null && !host.errorCode ? { status: "connecting" }
        : host.state === "running" && !host.errorCode ? { status: "running", serviceInstanceId: host.serviceInstanceId }
          : { status: "disconnected" }}
    projectNavigation={{
      directory, available: host.state === "running" && !host.errorCode && !busy,
      pending: workspacePending, error: workspaceError, folderInput, selection,
      openFolder: () => { void openFolder(); },
      closeFolder: () => setFolderInput(false),
      register: registerWorkspace,
      editWorkspace,
      hostKey: selectedId,
      inspectWorkspace: async (path, fingerprint, sessionId) => {
        const result = await webRequest<{ workspaces: { scopeFingerprint: string; inspection?: import("./WorkspaceInspection").Inspection }[] }>(
          { operation: "workspace", action: "inspect", path, fingerprint, sessionId }, requestConnection,
        );
        const workspace = result.workspaces[0];
        if (workspace?.scopeFingerprint !== fingerprint || !workspace.inspection) throw new Error("workspace_unavailable");
        return workspace.inspection;
      },
      openProjectPath: isTauri() && selectedId === "local" ? openLocalWorkspacePath : undefined,
      draftModels: async (path, modelId) => validateSessionModels(
        await webRequest({ operation: "workspace", action: "models", path, modelId }, connectionId.current),
      ),
      createChat,
      deleteChat,
      togglePin: (chat) => { void togglePin(chat); },
      select: openConversation,
    }} />
    <TrayHostDialog details={trayHosts.details} error={trayHosts.error}
      onClose={() => { trayHosts.closeDetails(); trayHosts.clearError(); }} onConfirm={trayHosts.confirmAction} />
  </>;
}
