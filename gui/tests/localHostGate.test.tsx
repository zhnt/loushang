import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LocalHostGate from "../src/LocalHostGate";

const native = vi.hoisted(() => ({
  invoke: vi.fn(), create: vi.fn(() => ({})), listeners: new Map<string, (value: any) => void>(),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: native.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async (name, callback) => {
  native.listeners.set(name, callback);
  return () => native.listeners.delete(name);
}) }));
vi.mock("../src/client/nativeLiveClient", () => ({ nativeLiveAvailable: async () => false, createNativeLiveClient: native.create }));
vi.mock("../src/DesktopFrame", () => ({ DesktopFrame: () => <header>Desktop</header> }));
vi.mock("../src/App", () => ({ default: () => <p>Fixture</p>, HarnessGui: () => <textarea aria-label="Draft" /> }));

beforeEach(() => {
  native.invoke.mockReset(); native.create.mockClear(); native.listeners.clear();
  native.invoke.mockImplementation(async (command, args) => {
    if (command === "local_host_environment") return { supported: true, workspace: "/workspace" };
    return args.request.action === "status" || args.request.action === "stop"
      ? { state: "not_running", errorCode: null, workspace: "/workspace" }
      : { state: "running", errorCode: null, workspace: "/workspace", instanceId: "instance-1" };
  });
});

describe("local managed Host presentation", () => {
  it("only inspects on startup and waits for an explicit start", async () => {
    render(<StrictMode><LocalHostGate /></StrictMode>);
    const start = await screen.findByRole("button", { name: "Start and connect" });
    expect(native.invoke.mock.calls.filter(([, args]) => args?.request?.action === "start")).toHaveLength(0);
    fireEvent.click(start);
    await screen.findByLabelText("Draft");
    expect(native.create).toHaveBeenCalledTimes(1);
    expect(native.invoke).toHaveBeenCalledWith("local_host_action", { request: { action: "start", workspace: "/workspace" } });
  });

  it("confirms Host stop and preserves the mounted draft across stop and start", async () => {
    render(<LocalHostGate />);
    fireEvent.click(await screen.findByRole("button", { name: "Start and connect" }));
    const draft = await screen.findByLabelText("Draft");
    fireEvent.change(draft, { target: { value: "unsent work" } });
    fireEvent.click(screen.getByRole("button", { name: "Stop Host" }));
    expect(native.invoke.mock.calls.filter(([, args]) => args?.request?.action === "stop")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop Host" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm shutdown" }));
    const start = await screen.findByRole("button", { name: "Start and connect" });
    expect(native.invoke).toHaveBeenCalledWith("local_host_action", { request: { action: "stop", workspace: "/workspace", instanceId: "instance-1" } });
    expect(screen.getByLabelText("Draft")).toBe(draft);
    expect(draft).toHaveValue("unsent work");
    fireEvent.click(start);
    await screen.findByRole("button", { name: "Reconnect" });
    expect(native.create).toHaveBeenCalledTimes(1);
  });

  it("refuses to offer another start when identity is unconfirmed", async () => {
    native.invoke.mockImplementation(async (command) => command === "local_host_environment"
      ? { supported: true, workspace: "/workspace" }
      : { state: "unknown", errorCode: "authentication_failed" });
    render(<LocalHostGate />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Host authentication failed");
    expect(screen.queryByRole("button", { name: "Start and connect" })).toBeNull();
  });

  it("shows unsupported platforms without attempting managed effects", async () => {
    native.invoke.mockResolvedValue({ supported: false, workspace: "/workspace" });
    render(<LocalHostGate />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Linux only"));
    expect(native.invoke.mock.calls.every(([name]) => name === "local_host_environment")).toBe(true);
  });
});
