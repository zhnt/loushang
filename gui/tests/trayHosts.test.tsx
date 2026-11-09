import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTrayHosts, type HostDirectory } from "../src/client/trayHosts";
const native = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true, invoke: native.invoke }));
const directory: HostDirectory = { selectedId: "local", connections: [
  { id: "local", name: "Local", kind: "local", selected: true, workspace: "/local", webUrl: "http://127.0.0.1:1422" },
  { id: "office", name: "Office", kind: "remote", selected: false, workspace: "", webUrl: "https://office.example" },
] };
function options() { return {
  enabled: true, selectedId: "local", localName: "Local Host", workspace: "/local", host: { state: "running" as const, errorCode: null, instanceId: "local-instance" },
  supported: true, busy: false, connection: "connected" as const, onSelect: vi.fn(async () => {}), onManage: vi.fn(async () => {}),
}; }
beforeEach(() => {
  native.invoke.mockReset();
  native.invoke.mockImplementation(async (_command, { request }) => {
    if (request.operation === "connections/list") return directory;
    if (request.request?.operation === "environment") return { supported: true, workspace: "/office" };
    return { state: "running", errorCode: null, instanceId: "office-instance", workspace: "/office" };
  });
});
describe("shared Host directory for the tray", () => {
  it("keeps per-Host identity and targets remote stop without changing the active connection", async () => {
    const props = options();
    const { result } = renderHook(() => useTrayHosts(props));
    await waitFor(() => expect(result.current.hosts[1]?.busy).toBe(false));
    expect(result.current.hosts[0].selected).toBe(true);
    expect(result.current.hosts[1].webUrl).toBe("https://office.example");
    act(() => result.current.action("office", "stop"));
    expect(result.current.details?.probe.host.instanceId).toBe("office-instance");
    expect(native.invoke.mock.calls.some(([, { request }]) => request.request?.action === "stop")).toBe(false);
    act(() => result.current.confirmStop());
    await waitFor(() => expect(native.invoke).toHaveBeenCalledWith("client_settings", { request: {
      operation: "host/request", connectionId: "office", request: { operation: "manage", action: "stop", workspace: "/office", instanceId: "office-instance" },
    } }));
    expect(props.onManage).not.toHaveBeenCalled();
    expect(props.onSelect).not.toHaveBeenCalled();
  });
  it("routes active Host reconnect to the mounted client owner and serializes selection", async () => {
    const props = options();
    const { result } = renderHook(() => useTrayHosts(props));
    await waitFor(() => expect(result.current.hosts).toHaveLength(2));
    await act(async () => result.current.action("local", "reconnect"));
    expect(props.onManage).toHaveBeenCalledWith("connect", "/local", "local-instance");
    await act(async () => { result.current.action("office", "enable"); result.current.action("office", "enable"); });
    expect(props.onSelect).toHaveBeenCalledTimes(1);
    expect(props.onSelect).toHaveBeenCalledWith("office");
  });
  it("does not route an old stop confirmation to a newly selected Host", async () => {
    const props = options();
    const { result, rerender } = renderHook((value) => useTrayHosts(value), { initialProps: props });
    await waitFor(() => expect(result.current.hosts).toHaveLength(2));
    act(() => result.current.action("local", "stop"));
    rerender({ ...props, selectedId: "office" });
    act(() => result.current.confirmStop());
    await waitFor(() => expect(native.invoke).toHaveBeenCalledWith("client_settings", { request: {
      operation: "host/request", connectionId: "local", request: { operation: "manage", action: "stop", workspace: "/local", instanceId: "local-instance" },
    } }));
    expect(props.onManage).not.toHaveBeenCalled();
  });
});
