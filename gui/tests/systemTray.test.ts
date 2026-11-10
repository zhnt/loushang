import { describe, expect, it } from "vitest";
import { availableTrayAction, trayProjection, type TrayHost } from "../src/client/systemTray";
const local: TrayHost = { id: "local", name: "Local", selected: true, connection: "disconnected", service: "running", busy: false, manageable: true, webUrl: "http://localhost:8080" };
describe("system tray projection", () => {
  it("separates connection health, selected Host and service state", () => {
    const view = trayProjection({ userName: "Chester", language: "en-US", hosts: [local,
      { ...local, id: "other", name: "Other", selected: false, connection: "connected" },
    ] }, 7);
    expect(view.userName).toBe("Chester");
    expect(view.currentLabel).toContain("🔴 Local · Disconnected");
    expect(view.hosts).toEqual([{ id: "local", label: "🔴 Local ✓" }, { id: "other", label: "🟢 Other" }]);
    expect(availableTrayAction(local, "enable")).toBe(false);
    expect(availableTrayAction(local, "stop")).toBe(true);
    expect(view.webUrl).toBe(local.webUrl);
    const connected = trayProjection({ userName: "Chester", language: "zh-CN", hosts: [{ ...local, connection: "connected" }] }, 8);
    expect(connected.currentLabel).toBe("当前 Host：🟢 Local");
  });
  it("shows connecting in yellow and never borrows another Host's web address", () => {
    const connecting: TrayHost = { ...local, connection: "connecting", busy: true, webUrl: undefined };
    const view = trayProjection({ userName: "", language: "zh-CN", hosts: [
      connecting,
      { ...local, id: "other", selected: false },
    ] }, 1);
    expect(view.currentLabel).toContain("🟡 Local · 正在连接…");
    expect(view.webUrl).toBeNull();
    expect(availableTrayAction(connecting, "stop")).toBe(false);
    expect(availableTrayAction(connecting, "reconnect")).toBe(false);
  });
  it("keeps unknown and unsupported services non-actionable", () => {
    expect(availableTrayAction({ ...local, service: "unknown" }, "start")).toBe(false);
    expect(availableTrayAction({ ...local, manageable: false }, "stop")).toBe(false);
    expect(availableTrayAction({ ...local, busy: true }, "info")).toBe(true);
    expect(availableTrayAction({ ...local, selected: false, canEnable: false }, "enable")).toBe(false);
    expect(availableTrayAction({ ...local, service: "unknown", manageable: false }, "reconnect")).toBe(true);
    expect(availableTrayAction({ ...local, service: "stopped" }, "start")).toBe(true);
    expect(trayProjection({ userName: "", language: "en", hosts: [] }, 1).currentLabel).toContain("No Host selected");
  });
});
