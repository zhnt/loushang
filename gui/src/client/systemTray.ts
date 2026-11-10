import enShell from "../i18n/locales/en-US/shell.json";
import zhShell from "../i18n/locales/zh-CN/shell.json";
import { useEffect, useRef } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export type TrayAction = "enable" | "info" | "reconnect" | "start" | "stop";
export type TrayConnection = "connected" | "connecting" | "disconnected" | "unknown";
export interface TrayHost {
  id: string;
  name: string;
  selected: boolean;
  connection: TrayConnection;
  service: "running" | "stopped" | "starting" | "stopping" | "unknown";
  busy: boolean;
  manageable: boolean;
  canStop?: boolean;
  canEnable?: boolean;
  configureStart?: boolean;
  webUrl?: string;
}
export interface TrayModel { userName: string; language: string; hosts: TrayHost[] }
const labels = { zh: zhShell.tray, en: enShell.tray };
const dots: Record<TrayConnection, string> = { connected: "🟢", connecting: "🟡", disconnected: "🔴", unknown: "⚪" };
export function availableTrayAction(host: TrayHost, action: TrayAction): boolean {
  if (action === "info") return true;
  if (host.busy) return false;
  if (action === "enable") return !host.selected && host.canEnable !== false;
  // Reconnect is also the recovery path when status/identity is unavailable.
  if (action === "reconnect") return true;
  if (!host.manageable) return false;
  if (action === "start") return host.service === "stopped" || host.configureStart === true;
  return host.service === "running" && host.canStop !== false;
}
export function trayProjection(model: TrayModel, revision: number) {
  const text = labels[model.language.startsWith("zh") ? "zh" : "en"];
  const separator = model.language.startsWith("zh") ? "：" : ": ";
  const current = model.hosts.find((host) => host.selected);
  const status = current && current.connection !== "connected" ? ` · ${text[current.connection]}` : "";
  return {
    revision, userName: model.userName || text.user,
    currentLabel: current ? `${text.current}${separator}${dots[current.connection]} ${current.name}${status}` : `⚪ ${text.none}`,
    showLabel: text.showLabel, webLabel: text.webLabel, manageLabel: text.manageLabel,
    quitLabel: text.quitLabel, enableLabel: text.enableLabel, infoLabel: text.infoLabel,
    reconnectLabel: text.reconnectLabel, stopLabel: text.stopLabel,
    webUrl: current?.webUrl ?? null,
    hosts: model.hosts.map((host) => ({
      id: host.id, label: `${dots[host.connection]} ${host.name}${host.selected ? " ✓" : ""}`,
      serviceLabel: `${text.service}${separator}${text[host.service]}`,
      startLabel: host.configureStart ? `${text.startLabel}…` : text.startLabel,
      enable: availableTrayAction(host, "enable"), reconnect: availableTrayAction(host, "reconnect"),
      start: availableTrayAction(host, "start"), stop: availableTrayAction(host, "stop"),
    })),
  };
}
let nextRevision = 0;
let updates: Promise<unknown> = Promise.resolve();
/** Serializes projections and ignores clicks from menus replaced during Host changes. */
export function useSystemTray(model: TrayModel, action: (hostId: string, action: TrayAction) => void, onError: (error: string) => void) {
  const latest = useRef({ model, action, onError });
  latest.current = { model, action, onError };
  const revision = useRef(0);
  const ready = useRef<Promise<unknown>>(Promise.resolve());
  useEffect(() => {
    if (!isTauri()) return;
    let active = true;
    const release = listen<{ revision: number; hostId: string; action: TrayAction }>("gui://tray-host-action", ({ payload }) => {
      if (!active || payload.revision !== revision.current) return;
      const host = latest.current.model.hosts.find((item) => item.id === payload.hostId);
      if (host && ["enable", "info", "reconnect", "start", "stop"].includes(payload.action) && availableTrayAction(host, payload.action)) {
        latest.current.action(payload.hostId, payload.action);
      }
    });
    ready.current = release;
    const errors = listen<string>("gui://tray-error", ({ payload }) => { if (active) latest.current.onError(payload); });
    return () => { active = false; void release.then((stop) => stop()); void errors.then((stop) => stop()); };
  }, []);
  const key = JSON.stringify(model);
  useEffect(() => {
    if (!isTauri()) return;
    const current = ++nextRevision;
    revision.current = current;
    const projection = trayProjection(latest.current.model, current);
    updates = updates.catch(() => {}).then(async () => {
      await ready.current;
      if (revision.current === current) await invoke("sync_tray", { projection });
    }).catch((error) => { console.warn("Unable to update system tray", error); });
  }, [key]);
}
