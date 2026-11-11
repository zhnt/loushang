import { invoke, isTauri } from "@tauri-apps/api/core";

export async function webRequest<T>(request: Record<string, unknown>, connectionId?: string): Promise<T> {
  const bound = connectionId ? { operation: "host/request", connectionId, request } : request;
  if (isTauri()) return invoke<T>("client_settings", { request: connectionId ? bound : { operation: "remote-call", request } });
  const response = await fetch("/api/loushang", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Loushang-Client": "1" },
    body: JSON.stringify(bound), signal: AbortSignal.timeout(80_000),
  });
  const value = await response.json();
  if (!response.ok || value.error) throw new Error(value.error ?? "host_unavailable");
  return value.result as T;
}

export function sharedSettings<T>(request: Record<string, unknown>): Promise<T> {
  return isTauri() ? invoke<T>("client_settings", { request }) : webRequest<T>(request);
}
