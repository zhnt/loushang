import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
const native = vi.hoisted(() => ({
  enabled: true,
  invoke: vi.fn(async () => {}),
  minimize: vi.fn(async () => {}), toggleMaximize: vi.fn(async () => {}), close: vi.fn(async () => {}),
  isMaximized: vi.fn(async () => false), onResized: vi.fn(async () => () => {}),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => native.enabled, invoke: native.invoke }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => native }));
vi.mock("../src/client/nativeFixtureBridge", () => ({ probeFixtureBridge: async () => ({ status: "locked", label: "Native bridge locked" }) }));
import { i18n } from "../src/i18n";
import { act } from "@testing-library/react";
import { DesktopFrame } from "../src/DesktopFrame";
import { HarnessGui } from "../src/App";
import { createMockAppClient } from "./support/mockAppClient";

it("labels disconnected execution snapshots and never waits on an empty completed record", async () => {
  const fixture = createMockAppClient();
  const snapshot = await fixture.snapshot();
  render(<HarnessGui client={{
    snapshot: async () => ({ ...snapshot, connection: "disconnected", source: {
      kind: "live", serviceInstanceId: "stopped-service", muxSpaceId: "mux", connectionEpoch: "1",
    }, sessions: snapshot.sessions.map((session) => ({ ...session,
      messages: [{ id: "empty-history", role: "assistant", content: "", phase: "complete" }],
      execution: { id: "old-execution", status: "running", revision: 1,
        interruptRequested: false, sourceStatus: "running", finalCursor: null, truncated: false },
    })) }),
    subscribe: () => () => {},
    submitText: fixture.submitText,
    interrupt: fixture.interrupt,
  }} />);
  expect(await screen.findByText("No text output was recorded.")).toBeVisible();
  expect(screen.getByText("Last known execution state: Running (disconnected)")).toBeVisible();
  expect(screen.queryByText("Waiting for output…")).toBeNull();
});

it("omits the entire desktop frame on the web", () => {
  native.enabled = false;
  try {
    const view = render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
    expect(view.container).toBeEmptyDOMElement();
  } finally { native.enabled = true; }
});

it("keeps back and forward controls and invokes available navigation", async () => {
  const back = vi.fn(), forward = vi.fn();
  const view = render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} onBack={back} />);
  const user = userEvent.setup();
  expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(back).toHaveBeenCalledOnce();
  view.rerender(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} onForward={forward} />);
  expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Forward" }));
  expect(forward).toHaveBeenCalledOnce();
});

it("navigates real Session selections with drafts intact and connects menu actions", async () => {
  const user = userEvent.setup();
  render(<HarnessGui client={createMockAppClient()} />);
  await screen.findByRole("heading", { name: "GUI development" });
  await user.type(screen.getByRole("textbox"), "retained draft");
  await user.click(screen.getByRole("button", { name: "Operational ontology · Idle" }));
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "GUI development" })).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("retained draft");
  await user.click(screen.getByRole("button", { name: "Forward" }));
  expect(screen.getByRole("heading", { name: "Operational ontology" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "File" }));
  await user.click(screen.getByRole("menuitem", { name: "Focus message input" }));
  expect(screen.getByRole("textbox")).toHaveFocus();
});

describe("native frame commands", () => {
  it("routes window buttons to the native window, not fixture execution", async () => {
    const user = userEvent.setup();
    render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
    for (const name of ["Minimize window", "Maximize window", "Close window"]) {
      const button = screen.getByRole("button", { name });
      expect(button.textContent).toBe("");
      const icon = button.querySelector("svg");
      expect(icon).toHaveAttribute("viewBox", "0 0 12 12");
      expect(icon).toHaveAttribute("width", "12");
      expect(icon).toHaveAttribute("height", "12");
      expect(icon).toHaveAttribute("stroke-width", "1");
      expect(icon).toHaveAttribute("aria-hidden", "true");
    }
    await user.click(screen.getByRole("button", { name: "Minimize window" }));
    await user.click(screen.getByRole("button", { name: "Maximize window" }));
    await user.click(screen.getByRole("button", { name: "Close window" }));
    expect(native.minimize).toHaveBeenCalledOnce();
    expect(native.toggleMaximize).toHaveBeenCalledOnce();
    expect(native.close).toHaveBeenCalledOnce();
  });
  it("shows restore for maximized windows and reports command failure", async () => {
    native.isMaximized.mockResolvedValueOnce(true);
    native.toggleMaximize.mockRejectedValueOnce(new Error("denied"));
    const user = userEvent.setup();
    render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
    const restore = await screen.findByRole("button", { name: "Restore window" });
    expect(restore.querySelector("svg")).toHaveAttribute("viewBox", "0 0 12 12");
    await user.click(restore);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Window action failed"));
  });
});

it("updates existing desktop controls without reinstalling native listeners", async () => {
  const user = userEvent.setup();
  native.onResized.mockClear();
  native.minimize.mockClear();
  render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
  await act(() => i18n.changeLanguage("zh-CN"));
  expect(screen.getByText("文件")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "最小化窗口" }));
  expect(native.minimize).toHaveBeenCalledOnce();
  expect(native.onResized).toHaveBeenCalledOnce();
});
it("localizes a window-state failure already visible when the language changes", async () => {
  native.isMaximized.mockRejectedValueOnce(new Error("unavailable"));
  render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Window state unavailable");
  await act(() => i18n.changeLanguage("zh-CN"));
  expect(screen.getByRole("alert")).toHaveTextContent("无法获取窗口状态");
});
it("reports an unavailable native resize subscription", async () => {
  native.onResized.mockRejectedValueOnce(new Error("unavailable"));
  render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Window resize notifications unavailable");
});
it("releases a native subscription that resolves after unmount", async () => {
  let subscribed: ((stop: () => void) => void) | undefined;
  native.onResized.mockImplementationOnce(() => new Promise((resolve) => { subscribed = resolve; }));
  const stop = vi.fn();
  const view = render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
  view.unmount();
  await act(async () => { subscribed?.(stop); });
  expect(stop).toHaveBeenCalledOnce();
});
