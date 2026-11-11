import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LocalHostGate from "../src/LocalHostGate";
const backend = vi.hoisted(() => ({ invoke: vi.fn(), settings: vi.fn(), create: vi.fn(), listeners: new Map<string, (event: any) => void>() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: backend.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: async (name: string, callback: (event: any) => void) => {
  backend.listeners.set(name, callback);
  return () => { if (backend.listeners.get(name) === callback) backend.listeners.delete(name); };
} }));
vi.mock("../src/client/hostApi", () => ({
  sharedSettings: (request: any) => backend.settings(request),
  webRequest: (request: any, id?: string) => backend.settings({ operation: "host/request", connectionId: id, request }),
}));
vi.mock("../src/client/nativeLiveClient", () => ({ nativeLiveAvailable: async () => false }));
vi.mock("../src/client/webLiveClient", () => ({ createWebLiveClient: backend.create }));
vi.mock("../src/App", () => ({ default: () => null, HarnessGui: ({ client, hostSettings, hostSettingsRequest, onConnectionChange }: {
  client: { id: string } | null; hostSettings: ReactNode; hostSettingsRequest: number; onConnectionChange: (state: string) => void;
}) => {
  const [draft, setDraft] = useState("");
  useEffect(() => onConnectionChange(client ? "connected" : "disconnected"), [client, onConnectionChange]);
  return <main><p>{client?.id ?? "offline"}</p><textarea aria-label="Draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
    {hostSettingsRequest > 0 ? <section aria-label="Host settings">{hostSettings}</section> : hostSettings}
  </main>;
} }));
const saved = [
  { id: "local", kind: "local", name: "Local", workspace: "/local", webUrl: "http://127.0.0.1:1422" },
  { id: "office", kind: "remote", name: "Office", workspace: "/office", webUrl: "https://office.example" },
];
let selected: string;
beforeEach(() => {
  selected = "local";
  backend.invoke.mockReset(); backend.settings.mockReset(); backend.create.mockReset(); backend.listeners.clear();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  backend.create.mockImplementation((workspace, id) => ({ workspace, id }));
  backend.settings.mockImplementation(async (request) => {
    if (request.operation === "connections/select") selected = request.connectionId;
    if (request.operation === "connections/list" || request.operation === "connections/select") return {
      selectedId: selected, connections: saved.map((entry) => ({ ...entry, selected: entry.id === selected })),
    };
    const id = request.connectionId ?? selected;
    const input = request.operation === "host/request" ? request.request : request;
    if (input.operation === "environment") return { supported: true, workspace: `/${id}`, connectionId: id };
    if (input.operation === "manage") return { state: "running", errorCode: null, workspace: `/${id}`, instanceId: `${id}-instance` };
    throw new Error("Unexpected request");
  });
  backend.invoke.mockImplementation(async (command, args) => {
    if (command === "offline_account") return { name: "Chester", id: "local-profile" };
    if (command === "client_settings") return backend.settings(args.request);
  });
});
function projection() {
  const calls = backend.invoke.mock.calls.filter(([command]) => command === "sync_tray");
  return calls[calls.length - 1]?.[1].projection;
}
function click(id: string, action: string) {
  act(() => backend.listeners.get("gui://tray-host-action")?.({ payload: { hostId: id, action, revision: projection().revision } }));
}
describe("tray selection integration", () => {
  it("opens Host settings from Start when the local Host cannot be reached and starts a newly chosen workspace", async () => {
    const settings = backend.settings.getMockImplementation()!;
    backend.settings.mockImplementation(async (request) => {
      const action = request.connectionId === "local" ? request.request?.action : null;
      if (action === "connect") return {
        state: "unknown", errorCode: "connection_unavailable", instanceId: "old-instance", workspace: "/local",
      };
      if (action === "start") return {
        state: "running", errorCode: null, instanceId: "new-instance", workspace: request.request.workspace,
      };
      return settings(request);
    });
    render(<LocalHostGate />);
    await waitFor(() => expect(projection()?.hosts[0]).toMatchObject({ start: true, startLabel: "Start…" }));
    click("local", "start");
    expect(await screen.findByRole("region", { name: "Host settings" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("connection_unavailable");
    expect(backend.settings.mock.calls.some(([request]) => request.request?.action === "start")).toBe(false);
    fireEvent.change(screen.getByDisplayValue("/local"), { target: { value: "/new-workspace" } });
    fireEvent.click(screen.getByRole("button", { name: /start and connect/i }));
    await waitFor(() => expect(backend.create).toHaveBeenCalledWith("/new-workspace", "local"));
    expect(backend.settings).toHaveBeenCalledWith({ operation: "host/request", connectionId: "local",
      request: { operation: "manage", action: "start", workspace: "/new-workspace" } });
  });
  it("switches the bound client and Web destination while retaining the mounted draft", async () => {
    render(<LocalHostGate />);
    await waitFor(() => expect(projection()?.hosts[1]?.enable).toBe(true));
    const draft = screen.getByLabelText("Draft");
    // Flush the queued tray projection before clicking its revisioned menu.
    await act(async () => { fireEvent.change(draft, { target: { value: "Unsent work" } }); });
    click("office", "enable");
    await waitFor(() => expect(backend.create).toHaveBeenCalledWith("/office", "office"));
    await waitFor(() => expect(projection().currentLabel).toContain("🟢 Office"));
    expect(projection().webUrl).toBe("https://office.example");
    expect(backend.settings).toHaveBeenCalledWith({ operation: "host/request", connectionId: "office",
      request: { operation: "manage", action: "connect", workspace: "/office" } });
    expect(screen.getByLabelText("Draft")).toBe(draft);
    expect(draft).toHaveValue("Unsent work");
    expect(backend.settings.mock.calls.some(([request]) => ["start", "stop"].includes(request.request?.action))).toBe(false);
  });
  it("retains the previous client and opens an error when saving the selection fails", async () => {
    render(<LocalHostGate />);
    await waitFor(() => expect(projection()?.hosts[1]?.enable).toBe(true));
    const implementation = backend.settings.getMockImplementation()!;
    backend.settings.mockImplementation(async (request) => {
      if (request.operation === "connections/select") throw new Error("read_only_config");
      return implementation(request);
    });
    click("office", "enable");
    expect(await screen.findByRole("alert")).toHaveTextContent("connection_failed");
    await waitFor(() => expect(projection().currentLabel).toContain("Local Host"));
    expect(projection().webUrl).toBe("http://127.0.0.1:1422");
    expect(backend.create).not.toHaveBeenCalledWith("/office", "office");
    expect(backend.invoke).toHaveBeenCalledWith("show_tray_window");
  });
});
