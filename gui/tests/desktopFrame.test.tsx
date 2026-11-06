import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
const native = vi.hoisted(() => ({
  minimize: vi.fn(async () => {}), toggleMaximize: vi.fn(async () => {}), close: vi.fn(async () => {}),
  isMaximized: vi.fn(async () => false), onResized: vi.fn(async () => () => {}),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => native }));
import { i18n } from "../src/i18n";
import { act } from "@testing-library/react";
import { DesktopFrame } from "../src/DesktopFrame";

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
