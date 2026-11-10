import { StrictMode, useEffect, useRef, type ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OfflineAccount } from "../src/client/offlineAccount";
import { AccountMenu } from "../src/AccountMenu";
import { SettingsDialog } from "../src/SettingsDialog";
import { readMarkdownPreferences } from "../src/markdown/preferences";
import LocalHostGate from "../src/LocalHostGate";

const native = vi.hoisted(() => ({
  invoke: vi.fn(), create: vi.fn(() => ({})), listeners: new Map<string, (value: any) => void>(),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: native.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (name, callback) => {
  native.listeners.set(name, callback);
  return () => native.listeners.delete(name);
}) }));
vi.mock("../src/client/nativeLiveClient", () => ({ nativeLiveAvailable: async () => false }));
vi.mock("../src/client/webLiveClient", () => ({ createWebLiveClient: native.create }));
vi.mock("../src/DesktopFrame", () => ({ DesktopFrame: () => <header>Desktop</header> }));
vi.mock("../src/App", () => ({
  default: () => <p>Fixture</p>,
  HarnessGui: ({ client, account, hostSettings, hostSettingsRequest = 0 }: { client: unknown; account: OfflineAccount | null; hostSettings: ReactNode; hostSettingsRequest?: number }) => {
    const dialog = useRef<HTMLDialogElement>(null);
    useEffect(() => { if (hostSettingsRequest) dialog.current?.showModal(); }, [hostSettingsRequest]);
    return <>
      {client ? <textarea aria-label="Draft" /> : <p>Disconnected workspace</p>}
      <AccountMenu account={account} onSettings={() => dialog.current?.showModal()} />
      <SettingsDialog dialogRef={dialog} hostSettings={hostSettings} hostRequest={hostSettingsRequest}
        markdown={readMarkdownPreferences()} onMarkdownChange={() => {}} />
    </>;
  },
}));

function openSettings() {
  fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  return within(screen.getByRole("dialog", { name: "Settings" }));
}

function openHostSettings() {
  const settings = openSettings();
  fireEvent.click(settings.getByRole("button", { name: "Host" }));
  return settings;
}

function installMock(implementation: (command: string, args?: any) => Promise<unknown>) {
  native.invoke.mockImplementation(async (command, args) => {
    if (command === "client_settings") {
      if (args.request.operation === "connections/list") return { selectedId: "local", connections: [
        { id: "local", name: "Local", kind: "local", selected: true, workspace: "/workspace", webUrl: null },
      ] };
      if (args.request.operation === "environment") return {
        ...await implementation("environment", args) as object, connectionId: "local",
      };
      if (args.request.operation === "host/request") return implementation("manage", { request: args.request.request });
    }
    return implementation(command, args);
  });
}

function management(action: string, workspace = "/workspace", instanceId?: string) {
  return { request: { operation: "host/request", connectionId: "local",
    request: { operation: "manage", action, workspace, ...(instanceId ? { instanceId } : {}) } } };
}

function countActions(action: string) {
  return native.invoke.mock.calls.filter(([, args]) => args?.request?.request?.action === action).length;
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  native.invoke.mockReset(); native.create.mockClear(); native.listeners.clear();
  installMock(async (command, args) => {
    if (command === "offline_account") return { name: "desktop-user", id: "local-test-id" };
    if (command === "sync_tray") return;
    if (command === "environment") return { supported: true, workspace: "/workspace" };
    return ["connect", "status", "stop"].includes(args.request.action)
      ? { state: "not_running", errorCode: null, workspace: "/workspace" }
      : { state: "running", errorCode: null, workspace: "/workspace", instanceId: "instance-1", serviceInstanceId: "service-1", pid: 123 };
  });
});

describe("local managed Host presentation", () => {
  it("routes tray start and stop through management and the existing shutdown confirmation", async () => {
    render(<LocalHostGate />);
    const projection = () => {
      const calls = native.invoke.mock.calls.filter(([name]) => name === "sync_tray");
      return calls[calls.length - 1]?.[1].projection;
    };
    await waitFor(() => expect(projection()?.hosts[0]?.start).toBe(true));
    expect(projection().userName).toBe("desktop-user");
    expect(projection().webUrl).toBeNull();
    const click = (revision: number, action: string) => act(() => native.listeners.get("gui://tray-host-action")?.({
      payload: { revision, hostId: "local", action },
    }));
    click(projection().revision - 1, "start");
    expect(countActions("start")).toBe(0);
    click(projection().revision, "start");
    await waitFor(() => expect(projection()?.hosts[0]?.stop).toBe(true));
    expect(projection().currentLabel).toContain("Connecting");
    click(projection().revision, "stop");
    expect(await screen.findByRole("alertdialog")).toBeVisible();
    expect(within(screen.getByRole("alertdialog")).getByText("instance-1", { exact: true })).toBeVisible();
    expect(countActions("stop")).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm shutdown" }));
    await waitFor(() => expect(native.invoke).toHaveBeenCalledWith("client_settings", management("stop", "/workspace", "instance-1")));
  });

  it("opens the shell, tries to reconnect and waits for an explicit start if offline", async () => {
    render(<StrictMode><LocalHostGate /></StrictMode>);
    expect(screen.getByText("Disconnected workspace")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Workspace" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    const profile = within(await screen.findByRole("region", { name: "Offline account" }));
    expect(profile.getByText("desktop-user")).toBeVisible();
    expect(profile.getByText("local-test-id")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const settings = within(screen.getByRole("dialog", { name: "Settings" }));
    expect(settings.queryByText("local-test-id")).toBeNull();
    expect(settings.getByRole("combobox", { name: "Interface language" })).toBeVisible();
    expect(settings.queryByRole("textbox", { name: "Workspace" })).not.toBeInTheDocument();
    fireEvent.click(settings.getByRole("button", { name: "Host" }));
    expect(settings.getByRole("textbox", { name: "Workspace" })).toBeVisible();
    expect(settings.queryByRole("combobox", { name: "Interface language" })).not.toBeInTheDocument();
    const start = await settings.findByRole("button", { name: "Start and connect" });
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("connect"));
    expect(countActions("start")).toBe(0);
    fireEvent.click(start);
    await screen.findByLabelText("Draft");
    const hostInfo = within(settings.getByRole("region", { name: "Host information" }));
    expect(hostInfo.getByText("123")).toBeVisible();
    expect(hostInfo.getByText("instance-1", { exact: true })).toBeVisible();
    expect(hostInfo.getByText("service-1", { exact: true })).toBeVisible();
    expect(native.create).toHaveBeenCalledTimes(1);
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("start"));
  });

  it("automatically enters a running Host without starting a process or opening Settings", async () => {
    installMock(async (command) => {
      if (command === "offline_account") return null;
      if (command === "environment") return { supported: true, workspace: "/previous" };
      return { state: "running", errorCode: null, workspace: "/previous", instanceId: "instance-1" };
    });
    render(<StrictMode><LocalHostGate /></StrictMode>);
    expect(await screen.findByLabelText("Draft")).toBeVisible();
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("connect", "/previous"));
    expect(countActions("start")).toBe(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms Host stop and preserves the mounted draft across stop and start", async () => {
    render(<LocalHostGate />);
    fireEvent.click(await openHostSettings().findByRole("button", { name: "Start and connect" }));
    const draft = await screen.findByLabelText("Draft");
    fireEvent.change(draft, { target: { value: "unsent work" } });
    (screen.getByRole("dialog") as HTMLDialogElement).open = false;
    expect(screen.queryByRole("button", { name: "Stop Host" })).not.toBeInTheDocument();
    openHostSettings();
    fireEvent.click(screen.getByRole("button", { name: "Stop Host" }));
    expect(countActions("stop")).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop Host" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm shutdown" }));
    const start = await screen.findByRole("button", { name: "Start and connect" });
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("stop", "/workspace", "instance-1"));
    expect(screen.getByLabelText("Draft")).toBe(draft);
    expect(draft).toHaveValue("unsent work");
    fireEvent.click(start);
    await screen.findByRole("button", { name: "Reconnect" });
    expect(native.create).toHaveBeenCalledTimes(1);
  });

  it("refuses to offer another start when identity is unconfirmed", async () => {
    installMock(async (command) => command === "environment"
      ? { supported: true, workspace: "/workspace" }
      : { state: "unknown", errorCode: "authentication_failed" });
    render(<LocalHostGate />);
    openHostSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent("Host authentication failed");
    expect(screen.queryByRole("button", { name: "Start and connect" })).toBeNull();
  });

  it("shows unsupported platforms without attempting managed effects", async () => {
    installMock(async () => ({ supported: false, workspace: "/workspace" }));
    render(<LocalHostGate />);
    openHostSettings();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Linux only"));
    expect(countActions("connect")).toBe(0);
  });
});
