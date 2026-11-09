import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import App, { HarnessGui } from "./App";
import { DesktopFrame } from "./DesktopFrame";
import { createNativeLiveClient, nativeLiveAvailable } from "./client/nativeLiveClient";
import type { HarnessClientUiPort } from "./client/model";
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
  const { t } = useTranslation("workspace");
  const [legacy, setLegacy] = useState(!isTauri());
  const [supported, setSupported] = useState<boolean | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [host, setHost] = useState<HostStatus>({ state: "unknown", errorCode: null });
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ action: "stop" | "restart"; workspace: string; instanceId?: string } | null>(null);
  const [client, setClient] = useState<HarnessClientUiPort | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const clientRef = useRef<HarnessClientUiPort | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);

  async function perform(action: Action, path = workspace, expected = host.instanceId) {
    if (pending.current || !path) return;
    const serial = ++generation.current;
    pending.current = true;
    setBusy(true);
    if (action === "start" || action === "restart") setHost((current) => ({ ...current, state: "starting", errorCode: null }));
    if (action === "stop") setHost((current) => ({ ...current, state: "stopping", errorCode: null }));
    try {
      const result = await invoke<HostStatus>("local_host_action", {
        request: { action, workspace: path, ...(expected ? { instanceId: expected } : {}) },
      });
      if (serial !== generation.current) return;
      if (!(result.state in states)) throw new Error("management_response_invalid");
      setHost(result);
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
      if (serial === generation.current) setHost({ state: "unknown", errorCode: typeof error === "string" ? error : "management_unconfirmed" });
    } finally {
      if (serial === generation.current) { pending.current = false; setBusy(false); }
    }
  }

  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    void (async () => {
      if (await nativeLiveAvailable()) { if (active) setLegacy(true); return; }
      const environment = await invoke<{ supported: boolean; workspace: string }>("local_host_environment");
      if (!active) return;
      setSupported(environment.supported);
      let selected = environment.workspace;
      try { selected = localStorage.getItem(WORKSPACE_KEY) ?? selected; } catch { /* Optional preference. */ }
      setWorkspace(selected);
      if (environment.supported) await perform("status", selected, undefined);
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

  if (legacy) return <App />;
  const reason = host.errorCode ?? (host.state === "running" ? connectionError : null);
  const errorLabel = reason && reason in errors ? t(errors[reason as keyof typeof errors])
    : reason?.startsWith("start_") || reason === "spawn_failed" ? t("localHost.errors.start")
    : reason?.startsWith("stop_") || reason === "cleanup_incomplete" ? t("localHost.errors.stop")
    : t("localHost.errors.unknown");
  const stop = (action: "stop" | "restart") => {
    setConfirmation({ action, workspace, instanceId: host.instanceId });
  };
  return <div className={`local-host-shell ${client ? "has-conversation" : ""}`}>
    {!client ? <DesktopFrame sidebarOpen={false} onToggleSidebar={() => undefined} /> : null}
    <section className="local-host-panel" aria-label={t("localHost.title")}>
      <strong>{t("localHost.title")}</strong>
      <label>{t("localHost.workspace")}
        <input value={workspace} disabled={!!client || busy} onChange={(event) => setWorkspace(event.target.value)} placeholder={t("localHost.pathHint")} />
      </label>
      <span role="status">{supported === false ? t("localHost.unsupported") : t(states[host.state])}</span>
      <div className="local-host-actions">
        <button disabled={busy || !supported || !workspace} onClick={() => void perform("status")}>{t("localHost.refresh")}</button>
        {host.state === "not_running" ? <button disabled={busy || !supported} onClick={() => void perform("start")}>{t("localHost.start")}</button> : null}
        {host.state === "running" ? <>
          <button disabled={busy} onClick={() => void perform("connect")}>{t(client ? "localHost.reconnect" : "localHost.connect")}</button>
          <button disabled={busy} onClick={() => stop("stop")}>{t("localHost.stop")}</button>
          <button disabled={busy} onClick={() => stop("restart")}>{t("localHost.restart")}</button>
        </> : null}
      </div>
      {reason ? <p role="alert">{errorLabel} <code>{reason}</code></p> : null}
      {host.instanceId ? <details><summary>{t("localHost.identity")}</summary><p>{t("localHost.pid")}: {host.pid ?? "—"}</p><code>{host.instanceId}</code><br /><code>{host.serviceInstanceId}</code></details> : null}
    </section>
    {confirmation ? <div className="local-host-confirm" role="alertdialog" aria-modal="true" aria-label={t("localHost.confirmTitle")} onKeyDown={(event) => { if (event.key === "Escape") setConfirmation(null); }}>
      <div><strong>{t("localHost.confirmTitle")}</strong><p>{t("localHost.confirmStop")}</p>
        <p>{confirmation.workspace}</p>
        <button autoFocus onClick={() => setConfirmation(null)}>{t("localHost.cancel")}</button>
        <button onClick={() => { const selected = confirmation; setConfirmation(null); void perform(selected.action, selected.workspace, selected.instanceId); }}>{t("localHost.confirm")}</button>
      </div>
    </div> : null}
    {client ? <div className="local-host-conversation"><HarnessGui client={client} /></div> : <p className="local-host-intro">{t("localHost.intro")}</p>}
  </div>;
}
