import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
const native = vi.hoisted(() => ({
  minimize: vi.fn(async () => {}), toggleMaximize: vi.fn(async () => {}), close: vi.fn(async () => {}),
  isMaximized: vi.fn(async () => false), onResized: vi.fn(async () => () => {}),
}));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => native }));
import { DesktopFrame } from "../src/DesktopFrame";

describe("native frame commands", () => {
  it("routes window buttons to the native window, not fixture execution", async () => {
    const user = userEvent.setup();
    render(<DesktopFrame sidebarOpen onToggleSidebar={() => {}} />);
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
    await user.click(await screen.findByRole("button", { name: "Restore window" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Window action failed"));
  });
});
