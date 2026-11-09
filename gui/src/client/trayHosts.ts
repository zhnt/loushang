import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import type { TrayAction, TrayConnection, TrayHost } from "./systemTray";

export type HostState = "unknown" | "not_running" | "starting" | "running" | "stopping" | "exited";
export type HostAction = "status" | "start" | "connect" | "stop" | "restart";
export interface HostStatus {
  state: HostState; errorCode: string | null; workspace?: string;
  instanceId?: string; serviceInstanceId?: string; pid?: number;
}
export interface SavedHost {
  id: string; name: string; kind: "local" | "remote"; selected: boolean;
  webUrl: string | null; workspace: string;
}
export interface HostDirectory { selectedId: string; connections: SavedHost[] }
interface HostProbe { host: HostStatus; workspace: string; supported: boolean; connection: TrayConnection }
export interface HostDetails { entry: SavedHost; probe: HostProbe; confirm: boolean }
const request = <T,>(request: Record<string, unknown>) => invoke<T>("client_settings", { request });
export const listTrayHosts = () => request<HostDirectory>({ operation: "connections/list" });
export const selectTrayHost = (connectionId: string) => request<HostDirectory>({ operation: "connections/select", connectionId });
const atHost = <T,>(connectionId: string, value: Record<string, unknown>) => request<T>({ operation: "host/request", connectionId, request: value });
const unknown = (workspace: string): HostProbe => ({ host: { state: "unknown", errorCode: null }, workspace, supported: false, connection: "unknown" });
const service = (state: HostState): TrayHost["service"] => state === "not_running" || state === "exited" ? "stopped" : state;

/** Saved connections come from the shared native configuration, never localStorage. */
export function useTrayHosts(options: {
  enabled: boolean; selectedId: string; localName: string; workspace: string; host: HostStatus; supported: boolean; busy: boolean;
  connection: TrayConnection;
  onSelect: (id: string) => Promise<void>;
  onManage: (action: HostAction, workspace?: string, instanceId?: string) => Promise<void>;
}) {
  const latest = useRef(options); latest.current = options;
  const [directory, setDirectory] = useState<HostDirectory | null>(null);
  const [probes, setProbes] = useState<Record<string, HostProbe>>({});
  const working = useRef(new Set<string>());
  const [workingIds, setWorkingIds] = useState<string[]>([]);
  const [switching, setSwitching] = useState(false);
  const switchingRef = useRef(false);
  const [details, setDetails] = useState<HostDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (error && isTauri()) void invoke("show_tray_window").catch(() => {});
  }, [error]);
  const active = useRef(true);
  const setWorking = (id: string, value: boolean) => {
    if (value) working.current.add(id); else working.current.delete(id);
    if (active.current) setWorkingIds([...working.current]);
  };
  async function probe(entry: SavedHost) {
    if (working.current.has(entry.id)) return;
    setWorking(entry.id, true);
    try {
      const environment = await atHost<{ workspace: string; supported: boolean }>(entry.id, { operation: "environment" });
      const host = environment.supported ? await atHost<HostStatus>(entry.id, {
        operation: "manage", action: "status", workspace: environment.workspace,
      }) : { state: "unknown" as const, errorCode: null };
      if (active.current) setProbes((old) => ({ ...old, [entry.id]: {
        host, workspace: environment.workspace, supported: environment.supported,
        connection: host.errorCode ? "disconnected" : "connected",
      } }));
    } catch {
      if (active.current) setProbes((old) => ({ ...old, [entry.id]: {
        ...unknown(entry.workspace), connection: "disconnected", host: { state: "unknown", errorCode: "connection_failed" },
      } }));
    } finally { setWorking(entry.id, false); }
  }
  useEffect(() => {
    active.current = true;
    if (!isTauri() || !options.enabled) return;
    let stopped = false;
    let refreshing = false;
    async function refresh() {
      if (refreshing || switchingRef.current) return;
      refreshing = true;
      try {
        const value = await listTrayHosts();
        if (stopped) return;
        setDirectory(value);
        await Promise.all(value.connections.filter((entry) => entry.id !== latest.current.selectedId).map(probe));
      } catch {
        // A failed refresh does not erase saved entries or invent connection facts.
        if (!stopped) setError("management_unavailable");
      } finally { refreshing = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => { stopped = true; active.current = false; window.clearInterval(timer); };
  }, [options.enabled]);

  function currentProbe(entry: SavedHost): HostProbe {
    return entry.selected ? { host: options.host, workspace: options.workspace,
      supported: options.supported, connection: options.connection } : probes[entry.id] ?? unknown(entry.workspace);
  }
  const entries = (directory?.connections ?? []).map((entry) => ({ ...entry, selected: entry.id === options.selectedId }));
  const hosts: TrayHost[] = entries.map((entry) => {
    const state = currentProbe(entry);
    return { id: entry.id, name: entry.kind === "local" ? options.localName : entry.name,
      selected: entry.selected, connection: state.connection, service: service(state.host.state),
      busy: switching || workingIds.includes(entry.id) || (entry.selected && options.busy),
      manageable: state.supported, canEnable: !options.busy && !switching,
      canStop: Boolean(state.host.instanceId), webUrl: entry.webUrl ?? undefined };
  });

  async function manage(entry: SavedHost, action: HostAction, state: HostProbe) {
    if (working.current.has(entry.id) || switchingRef.current) return;
    setWorking(entry.id, true); setError(null);
    try {
      if (entry.id === latest.current.selectedId) {
        await latest.current.onManage(action, state.workspace, state.host.instanceId);
      } else {
        if (action === "connect" && (!state.workspace || !state.supported)) {
          const environment = await atHost<{ workspace: string; supported: boolean }>(entry.id, { operation: "environment" });
          state = { ...state, workspace: environment.workspace, supported: environment.supported };
          if (!state.supported) throw new Error("platform_unsupported");
        }
        const host = await atHost<HostStatus>(entry.id, { operation: "manage", action,
          workspace: state.workspace, ...(state.host.instanceId ? { instanceId: state.host.instanceId } : {}) });
        if (active.current) setProbes((old) => ({ ...old, [entry.id]: { ...state, host,
          connection: host.errorCode ? "disconnected" : "connected" } }));
        if (host.errorCode) throw new Error(host.errorCode);
      }
    } catch { if (active.current) setError("management_unconfirmed"); }
    finally { setWorking(entry.id, false); }
  }
  function action(id: string, action: TrayAction) {
    const entry = entries.find((item) => item.id === id);
    if (!entry) return;
    const state = currentProbe(entry);
    if (action === "info" || action === "stop") {
      setDetails({ entry, probe: state, confirm: action === "stop" });
      return;
    }
    if (action === "enable") {
      if (switchingRef.current) return;
      switchingRef.current = true; setSwitching(true); setError(null);
      void latest.current.onSelect(id).then(async () => {
        const value = await listTrayHosts();
        if (active.current) setDirectory(value);
      }).catch(() => { if (active.current) setError("connection_failed"); })
        .finally(() => { switchingRef.current = false; if (active.current) setSwitching(false); });
    } else { void manage(entry, action === "start" ? "start" : "connect", state); }
  }
  function confirmStop() {
    if (!details?.confirm) return;
    const captured = details;
    setDetails(null);
    // Preserve the identity shown in the confirmation even if polling found a replacement.
    void manage(captured.entry, "stop", captured.probe);
  }
  return { hosts, action, details, closeDetails: () => setDetails(null), confirmStop, error,
    clearError: () => setError(null) };
}
