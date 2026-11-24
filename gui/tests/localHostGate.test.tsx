import { StrictMode, useEffect, useRef, useState, type ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OfflineAccount } from "../src/client/offlineAccount";
import { AccountMenu } from "../src/AccountMenu";
import { SettingsDialog } from "../src/SettingsDialog";
import { readMarkdownPreferences } from "../src/markdown/preferences";
import LocalHostGate from "../src/LocalHostGate";
import { ProjectNavigation } from "../src/ProjectNavigation";
import type { ManagedProjectNavigation } from "../src/client/projectDirectory";
import type { ClientSnapshot, HarnessClientUiPort } from "../src/client/model";
import { createMockAppClient } from "./support/mockAppClient";

const native = vi.hoisted(() => ({
  invoke: vi.fn(), create: vi.fn(() => ({ suspend: async () => () => {} })), listeners: new Map<string, (value: any) => void>(),
  available: vi.fn(async () => false), realShell: false,
}));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({ label: "main" }) }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: native.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (name, callback) => {
  native.listeners.set(name, callback);
  return () => native.listeners.delete(name);
}) }));
vi.mock("../src/client/nativeLiveClient", () => ({ nativeLiveAvailable: native.available }));
vi.mock("../src/client/webLiveClient", () => ({ createWebLiveClient: native.create, clientDirectoryControls: () => undefined }));
vi.mock("../src/DesktopFrame", () => ({ DesktopFrame: () => <header>Desktop</header>, PanelIcon: () => null }));
vi.mock("../src/App", async (importOriginal) => {
  const { HarnessGui } = await importOriginal<typeof import("../src/App")>();
  function StubShell({ client, account, hostSettings, hostSettingsRequest = 0, projectNavigation }: {
    projectNavigation?: ManagedProjectNavigation;
    client: unknown;
    account?: OfflineAccount | null;
    hostSettings?: ReactNode;
    hostSettingsRequest?: number;
  }) {
    const dialog = useRef<HTMLDialogElement>(null);
    const [draft, setDraft] = useState<{ path: string | null } | null>(null);
    useEffect(() => { if (hostSettingsRequest) dialog.current?.showModal(); }, [hostSettingsRequest]);
    if (!projectNavigation) return null;
    return <>
      <button disabled={!projectNavigation.available} onClick={() => setDraft({ path: null })}>New Session</button>
      <ProjectNavigation navigation={{ ...projectNavigation, create: (path) => setDraft({ path }) }}
        selectedId={projectNavigation.selection?.id ?? null} titles={{}} />
      {draft && <button onClick={() => void projectNavigation.createChat(draft.path, "continuity-test", "New Session")
        .then((binding) => binding?.show(binding.sessionId))}>Send first message</button>}
      {client ? <textarea aria-label="Draft" /> : <p>Disconnected workspace</p>}
      <AccountMenu account={account} onSettings={() => dialog.current?.showModal()} />
      <SettingsDialog dialogRef={dialog} hostSettings={hostSettings} hostRequest={hostSettingsRequest}
        markdown={readMarkdownPreferences()} onMarkdownChange={() => {}} />
    </>;
  }
  return {
    default: () => <p>Fixture</p>,
    HarnessGui: (props: Parameters<typeof HarnessGui>[0]) =>
      native.realShell ? <HarnessGui {...props} /> : <StubShell {...props} />,
  };
});

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
  const pinned = new Set<string>();
  const created: string[] = [];
  const chat = (id: string, title: string, scope: string) => ({ id, title, scope, pinned: pinned.has(id) });
  native.invoke.mockImplementation(async (command, args) => {
    if (command === "client_settings") {
      if (args.request.operation === "connections/list") return { selectedId: "local", connections: [
        { id: "local", name: "Local", kind: "local", selected: true, workspace: "/workspace", webUrl: null },
      ] };
      if (args.request.operation === "environment") return {
        ...await implementation("environment", args) as object, connectionId: "local",
      };
      if (args.request.operation === "host/request") {
        if (args.request.request.operation === "preferences") {
          const { action, session } = args.request.request;
          if (action === "pin") pinned.add(session);
          if (action === "unpin") pinned.delete(session);
          return { pinned: [...pinned], recent: [], selected: "" };
        }
        if (args.request.request.operation === "workspace") {
          const request = args.request.request;
          if (request.action === "create") {
            const result = await implementation("workspace", request);
            created.push(request.path);
            return result;
          }
          if (request.action !== "navigation") return implementation("workspace", request);
          return { projects: [
            ...created.map((path) => ({ path, sessions: [] })),
            { path: "/workspace", sessions: [chat("a", "Project A chat", "mux:a")] },
            { path: "/previous", sessions: [chat("b", "Project B chat", "mux:b")] },
          ], temporarySessions: [chat("scratch", "Temporary chat", "mux:temp")] };
        }
        return { manageable: true, ...await implementation("manage", { request: args.request.request }) as object };
      }
    }
    return implementation(command, args);
  });
}

function management(action: string, _workspace = "/workspace", instanceId?: string) {
  return { request: { operation: "host/request", connectionId: "local",
    request: { operation: "manage", action, ...(instanceId ? { instanceId } : {}) } } };
}

function countActions(action: string) {
  return native.invoke.mock.calls.filter(([, args]) => args?.request?.request?.action === action).length;
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  native.invoke.mockReset(); native.create.mockClear(); native.listeners.clear(); native.realShell = false;
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
  it("finishes connecting when navigation fails and clears the warning after recovery", async () => {
    installMock(async (command) => {
      if (command === "offline_account") return { name: "desktop-user", id: "local-test-id" };
      if (command === "environment") return { supported: true, workspace: "/workspace" };
      return { state: "running", errorCode: null, instanceId: "instance-1" };
    });
    const implementation = native.invoke.getMockImplementation()!;
    let failed = true;
    native.invoke.mockImplementation(async (command, args) => {
      if (failed && args?.request?.request?.action === "navigation") throw new Error("operation_unavailable");
      return implementation(command, args);
    });
    render(<LocalHostGate />);
    await screen.findByText("Unable to open this workspace.");
    const projection = () => {
      const calls = native.invoke.mock.calls.filter(([name]) => name === "sync_tray");
      return calls[calls.length - 1]?.[1].projection;
    };
    await waitFor(() => {
      expect(projection()?.currentLabel).toBeDefined();
      expect(projection().currentLabel).not.toContain("Connecting");
    });
    failed = false;
    await waitFor(() => expect(screen.queryByText("Unable to open this workspace.")).toBeNull(), { timeout: 5000 });
  });

  it("does not query the Web Host directory while selecting a direct native connection", async () => {
    native.available.mockResolvedValueOnce(true);
    render(<LocalHostGate />);
    expect(await screen.findByText("Fixture")).toBeVisible();
    expect(native.invoke.mock.calls.filter(([command]) => command === "client_settings")).toEqual([]);
  });

  it("waits for another client to finish starting the Host", async () => {
    let checks = 0;
    installMock(async (command, args) => {
      if (command === "offline_account") return { name: "desktop-user", id: "local-test-id" };
      if (command === "sync_tray") return;
      if (command === "environment") return { supported: true, workspace: "/workspace" };
      if (args.request.action === "connect") {
        return { state: ++checks === 1 ? "starting" : "running", errorCode: null, instanceId: "instance-1" };
      }
      return { state: "running", errorCode: null, instanceId: "instance-1" };
    });
    render(<LocalHostGate />);
    const settings = openHostSettings();
    expect(await settings.findByText("Host starting")).toBeVisible();
    expect(await settings.findByText("Running", {}, { timeout: 3000 })).toBeVisible();
    expect(countActions("connect")).toBeGreaterThanOrEqual(2);
    expect(countActions("start")).toBe(0);
  });

  it("offers Start when the recorded Host has exited", async () => {
    installMock(async (command, args) => {
      if (command === "offline_account") return { name: "desktop-user", id: "local-test-id" };
      if (command === "sync_tray") return;
      if (command === "environment") return { supported: true, workspace: "/workspace" };
      return args.request.action === "start"
        ? { state: "running", errorCode: null, instanceId: "replacement" }
        : { state: "exited", errorCode: null };
    });
    render(<LocalHostGate />);
    const start = await openHostSettings().findByRole("button", { name: "Start and connect" });
    fireEvent.click(start);
    await waitFor(() => expect(countActions("start")).toBe(1));
  });

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
    expect(projection().currentLabel).toContain("Connected");
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
    const profile = within(await screen.findByRole("region", { name: "Local account" }));
    expect(profile.getByText("desktop-user")).toBeVisible();
    expect(screen.getByText("local-test-id")).not.toBeVisible();
    fireEvent.click(profile.getByRole("button", { name: /desktop-user.*Account details/ }));
    const details = within(screen.getByRole("dialog", { name: "Account details" }));
    expect(details.getByText("local-test-id")).toBeVisible();
    expect(details.getByRole("button", { name: "Copy local account ID" })).toBeVisible();
    fireEvent.click(details.getByRole("button", { name: "Close account details" }));
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const settings = within(screen.getByRole("dialog", { name: "Settings" }));
    expect(settings.queryByText("local-test-id")).toBeNull();
    expect(settings.getByRole("combobox", { name: "Interface language" })).toBeVisible();
    expect(settings.queryByRole("textbox", { name: "Workspace" })).not.toBeInTheDocument();
    fireEvent.click(settings.getByRole("button", { name: "Host" }));
    expect(settings.queryByRole("textbox", { name: "Workspace" })).toBeNull();
    expect(settings.queryByRole("combobox", { name: "Interface language" })).not.toBeInTheDocument();
    const start = await settings.findByRole("button", { name: "Start and connect" });
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("connect"));
    expect(countActions("start")).toBe(0);
    fireEvent.click(start);
    await waitFor(() => expect(screen.getByRole("button", { name: "New Session" })).toBeEnabled());
    const hostInfo = within(settings.getByRole("region", { name: "Host information" }));
    expect(hostInfo.getByText("123")).toBeVisible();
    expect(hostInfo.getByText("instance-1", { exact: true })).toBeVisible();
    expect(hostInfo.getByText("service-1", { exact: true })).toBeVisible();
    expect(native.create).not.toHaveBeenCalled();
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("start"));
  });

  it("opens the new conversation page with existing chats and no attached conversation", async () => {
    native.realShell = true;
    installMock(async (command) => {
      if (command === "offline_account") return null;
      if (command === "environment") return { supported: true, workspace: "/previous" };
      return { state: "running", errorCode: null, workspace: "/previous", instanceId: "instance-1" };
    });
    render(<StrictMode><LocalHostGate /></StrictMode>);
    expect(await screen.findByRole("button", { name: "Project B chat" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { name: "What would you like to work on?" })).toBeVisible();
    expect(screen.getByRole("textbox")).toBeEnabled();
    expect(native.create).not.toHaveBeenCalled();
    expect(countActions("create-chat")).toBe(0);
    expect(native.invoke).toHaveBeenCalledWith("client_settings", management("connect", "/previous"));
    expect(countActions("start")).toBe(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps projects visible and uses distinct actions for project and temporary chats", async () => {
    installMock(async (command, args) => {
      if (command === "environment") return { supported: true, workspace: "" };
      if (command === "pick_project_folder") return "C:\\Work\\项目";
      if (command === "workspace" && args.action === "create-chat") return args.path
        ? { workspace: args.path, sessionId: "a" }
        : { workspace: "@temporary", sessionId: "scratch" };
      return { state: "running", errorCode: null };
    });
    render(<LocalHostGate />);
    const projects = within(screen.getByRole("region", { name: "Projects" }));
    const chats = within(screen.getByRole("region", { name: "Chats" }));
    fireEvent.click(await projects.findByRole("button", { name: "Project B chat" }));
    expect(native.create).toHaveBeenCalledWith("/previous", "local");
    expect(projects.getByRole("button", { name: "Project A chat" })).toBeVisible();
    expect(chats.getByRole("button", { name: "Temporary chat" })).toBeVisible();
    expect(chats.queryByText("Project B chat")).toBeNull();

    const project = projects.getByRole("button", { name: "workspace" });
    fireEvent.click(project);
    expect(project).toHaveAttribute("aria-expanded", "false");
    expect(projects.queryByRole("button", { name: "Project A chat" })).toBeNull();
    expect(projects.getByRole("button", { name: "Project B chat" })).toBeVisible();
    fireEvent.click(projects.getByRole("button", { name: "New chat in workspace" }));
    expect(countActions("create-chat")).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Send first message" }));
    await waitFor(() => expect(native.create).toHaveBeenCalledWith("/workspace", "local"));
    expect(projects.getByRole("button", { name: "Project A chat" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "New Session" }));
    expect(countActions("create-chat")).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Send first message" }));
    await waitFor(() => expect(native.create).toHaveBeenCalledWith("@temporary", "local"));
    expect(chats.getByRole("button", { name: "Temporary chat" })).toHaveAttribute("aria-current", "true");

    fireEvent.click(projects.getByRole("button", { name: "Add project" }));
    await waitFor(() => expect(native.invoke).toHaveBeenCalledWith("client_settings", {
      request: { operation: "host/request", connectionId: "local",
        request: { operation: "workspace", action: "create-workspace", name: "项目", path: "C:\\Work\\项目", alias: "main" } },
    }));
    expect(countActions("create-chat")).toBe(2);
    expect(countActions("open")).toBe(0);
  });

  it("hides Workspace creation while keeping existing projects and Add project available", async () => {
    installMock(async (command) => command === "environment"
      ? { supported: true, workspace: "" }
      : { state: "running", errorCode: null });
    render(<LocalHostGate />);
    const projects = within(screen.getByRole("region", { name: "Projects" }));
    const add = projects.getByRole("button", { name: "Add project" });
    await waitFor(() => expect(add).toBeEnabled());
    expect(projects.getByRole("button", { name: "Project B chat" })).toBeVisible();
    expect(projects.queryByRole("button", { name: "New Workspace" })).not.toBeInTheDocument();
    expect(projects.queryByRole("textbox")).not.toBeInTheDocument();
    expect(countActions("create")).toBe(0);
  });

  it("shows a picker failure without opening a manual path field for the local desktop", async () => {
    installMock(async (command) => {
      if (command === "environment") return { supported: true, workspace: "" };
      if (command === "pick_project_folder") throw new Error("folder_picker_unavailable");
      return { state: "running", errorCode: null };
    });
    render(<LocalHostGate />);
    const projects = within(screen.getByRole("region", { name: "Projects" }));
    const button = projects.getByRole("button", { name: "Add project" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await projects.findByRole("alert")).toBeVisible();
    expect(projects.queryByRole("textbox")).not.toBeInTheDocument();
    expect(countActions("register")).toBe(0);
  });

  it("puts pinned project and temporary chats above projects and returns them to their groups", async () => {
    installMock(async (command) => command === "environment"
      ? { supported: true, workspace: "" }
      : { state: "running", errorCode: null });
    render(<LocalHostGate />);
    const projects = screen.getByRole("region", { name: "Projects" });
    const chats = screen.getByRole("region", { name: "Chats" });
    const pin = await within(projects).findByRole("button", { name: "Pin Project A chat" });
    pin.focus();
    fireEvent.click(pin);
    const pinned = await screen.findByRole("region", { name: "Pinned" });
    expect(pinned.nextElementSibling).toBe(projects);
    expect(within(pinned).getByRole("button", { name: "Unpin Project A chat" })).toHaveFocus();
    expect(within(projects).queryByRole("button", { name: "Project A chat" })).toBeNull();
    expect(native.invoke).toHaveBeenCalledWith("client_settings", {
      request: { operation: "host/request", connectionId: "local",
        request: { operation: "preferences", scope: "mux:a", session: "a", action: "pin" } },
    });
    fireEvent.click(within(chats).getByRole("button", { name: "Pin Temporary chat" }));
    await within(pinned).findByRole("button", { name: "Unpin Temporary chat" });
    expect(within(chats).queryByRole("button", { name: "Temporary chat" })).toBeNull();

    fireEvent.click(within(pinned).getByRole("button", { name: "Project A chat" }));
    expect(native.create).toHaveBeenCalledWith("/workspace", "local");
    fireEvent.click(within(projects).getByRole("button", { name: "workspace" }));
    fireEvent.click(within(pinned).getByRole("button", { name: "Unpin Project A chat" }));
    expect(await within(projects).findByRole("button", { name: "Project A chat" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(within(pinned).getByRole("button", { name: "Unpin Temporary chat" }));
    expect(await within(chats).findByRole("button", { name: "Temporary chat" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Pinned" })).toBeNull();
  });

  it("confirms Host stop and preserves the mounted draft across stop and start", async () => {
    render(<LocalHostGate />);
    fireEvent.click(await openHostSettings().findByRole("button", { name: "Start and connect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Project A chat" }));
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

  it("keeps the open conversation connecting until the replacement Host publishes a snapshot", async () => {
    native.realShell = true;
    const seed = await createMockAppClient().snapshot();
    const session = { ...seed.sessions[0], id: "a", status: "running" as const };
    const snapshot = (instance: string): ClientSnapshot => ({
      ...seed, sessions: [session], selectedSessionId: session.id, connection: "connected",
      source: { kind: "live", serviceInstanceId: instance, muxSpaceId: "mux", connectionEpoch: "1" },
    });
    let publish!: (snapshot: ClientSnapshot) => void;
    const client: HarnessClientUiPort & { suspend(): Promise<() => void> } = {
      snapshot: async () => snapshot("service-1"),
      subscribe: () => () => {},
      subscribeSnapshots: (listener) => { publish = listener; return () => {}; },
      submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
      interrupt: async () => ({ accepted: false }),
      suspend: async () => () => {},
    };
    native.create.mockReturnValueOnce(client);

    const running = (instance: number) => ({
      state: "running", errorCode: null, instanceId: `instance-${instance}`, serviceInstanceId: `service-${instance}`,
    });
    let finishRestart!: (status: ReturnType<typeof running>) => void;
    installMock(async (command, args) => {
      if (command === "offline_account") return { name: "desktop-user", id: "local-test-id" };
      if (command === "sync_tray") return;
      if (command === "environment") return { supported: true, workspace: "/workspace" };
      if (args.request.action === "restart") return new Promise((resolve) => { finishRestart = resolve; });
      return running(1);
    });

    const { container } = render(<LocalHostGate />);
    const chip = () => container.querySelector(".connection-chip");
    await waitFor(() => expect(chip()).toHaveTextContent(/^Connected$/));
    fireEvent.click(await screen.findByRole("button", { name: "Project A chat" }));
    const editor = await screen.findByRole("textbox", { name: /message/i });
    fireEvent.change(editor, { target: { value: "unsent during restart" } });
    const interrupt = screen.getByRole("button", { name: "Interrupt" });
    expect(interrupt).toBeEnabled();

    const settings = openHostSettings();
    fireEvent.click(settings.getByRole("button", { name: "Restart Host" }));
    expect(chip()).toHaveTextContent(/^Connected$/);
    fireEvent.click(within(settings.getByRole("alertdialog")).getByRole("button", { name: "Restart Host" }));
    expect(settings.getByText("Host starting")).toBeVisible();
    expect(chip()).toHaveTextContent(/^Connecting$/);
    expect(interrupt).toBeDisabled();

    await act(async () => finishRestart(running(2)));
    expect(settings.getByText("Running", { exact: true })).toBeVisible();
    act(() => publish(snapshot("service-1")));
    expect(chip()).toHaveTextContent(/^Connecting$/);
    expect(interrupt).toBeDisabled();

    act(() => publish(snapshot("service-2")));
    expect(chip()).toHaveTextContent(/^Connected$/);
    expect(editor).toHaveValue("unsent during restart");
    expect(interrupt).toBeEnabled();
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

  it("shows missing AppServer configuration without contacting a Host", async () => {
    installMock(async () => ({ supported: false, workspace: "/workspace" }));
    render(<LocalHostGate />);
    openHostSettings();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No AppServer connection is configured"));
    expect(countActions("connect")).toBe(0);
  });
});
