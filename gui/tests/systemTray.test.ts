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
    expect(view.hosts[0].label).toContain("✓");
    expect(view.hosts[0].serviceLabel).toBe("Service：Running");
    expect(view.hosts[1].label).toBe("🟢 Other");
    expect(view.hosts[1].enable).toBe(true);
    expect(view.hosts[0].enable).toBe(false);
    expect(view.hosts[0].stop).toBe(true);
    expect(view.webUrl).toBe(local.webUrl);
  });
  it("shows connecting in yellow and never borrows another Host's web address", () => {
    const view = trayProjection({ userName: "", language: "zh-CN", hosts: [
      { ...local, connection: "connecting", busy: true, webUrl: undefined },
      { ...local, id: "other", selected: false },
    ] }, 1);
    expect(view.currentLabel).toContain("🟡 Local · 正在连接…");
    expect(view.webUrl).toBeNull();
    expect(view.hosts[0].stop).toBe(false);
    expect(view.hosts[0].reconnect).toBe(false);
  });
  it("keeps unknown and unsupported services non-actionable", () => {
    expect(availableTrayAction({ ...local, service: "unknown" }, "start")).toBe(false);
    expect(availableTrayAction({ ...local, manageable: false }, "stop")).toBe(false);
    expect(availableTrayAction({ ...local, busy: true }, "info")).toBe(true);
    expect(availableTrayAction({ ...local, service: "stopped" }, "start")).toBe(true);
    expect(trayProjection({ userName: "", language: "en", hosts: [] }, 1).currentLabel).toContain("No Host selected");
  });
});
