import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, afterEach, vi } from "vitest";
import { HarnessGui } from "../../src/App";
import { createMockAppClient } from "../../src/client/mockAppClient";
import type { ClientSnapshot } from "../../src/client/model";
import config from "../../src-tauri/tauri.conf.json";
import capability from "../../src-tauri/capabilities/default.json";

describe("desktop frame", () => {
  it("uses shared icons and exposes unimplemented sidebar entries as unavailable", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });
    for (const name of ["Search unavailable", "Pull requests", "Scheduled", "Plugins"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button.querySelector("svg")).toHaveAttribute("viewBox", "0 0 24 24");
    }
    const rail = screen.getByLabelText("Workspace and Session navigation");
    expect(rail.textContent).not.toMatch(/[♢▱⌕]/);
    expect(rail.querySelectorAll('[data-icon="folder"]')).toHaveLength(3);
    expect(rail.querySelector('.brand-name [data-icon="chevron-down"]')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Work Dock" }));
    const close = screen.getByRole("button", { name: "Close Work Dock" });
    expect(close.querySelector('[data-icon="close"]')).toBeInTheDocument();
    await user.click(close);
    expect(screen.queryByLabelText("Work Dock")).not.toBeInTheDocument();
  });
  it("pins chats above workspace groups, keeps unassigned chats, and scopes pins to the mux", async () => {
    const user = userEvent.setup();
    const client = createMockAppClient();
    const fixture = await client.snapshot();
    function attached(muxSpaceId: string, serviceInstanceId: string) {
      return {
        subscribe: (listener: Parameters<typeof client.subscribe>[0]) => client.subscribe(listener),
        submitText: (input: Parameters<typeof client.submitText>[0]) => client.submitText(input),
        interrupt: (id: string) => client.interrupt(id),
        snapshot: async (): Promise<ClientSnapshot> => ({
          ...fixture,
          connection: "connected",
          source: { kind: "live", muxSpaceId, serviceInstanceId, connectionEpoch: "1" },
          capabilities: fixture.capabilities.map((capability) => capability.name === "workspace"
            ? { ...capability, availability: "live", version: "loushang.workspace/v1" } : capability),
          sessions: fixture.sessions.map((session) => session.title === "Operational ontology"
            ? { ...session, workspaceId: "" } : session),
        }),
      };
    }

    const first = render(<HarnessGui client={attached("sidebar-a", "host-one")} />);
    await screen.findByRole("heading", { name: "GUI development" });
    expect(screen.getByText("Without a workspace")).toBeVisible();
    const chats = screen.getByRole("region", { name: "Chats" });
    expect(within(chats).getAllByRole("button", { name: /Operational ontology ·/ })).toHaveLength(1);
    const workspace = within(chats).getByRole("button", { name: /^Loushang/ }).closest("section")!;
    await user.click(within(workspace).getByRole("button", { name: /^Provider review ·/ }));
    expect(workspace.querySelector(".session-item")).toHaveTextContent("Provider review");
    await user.click(within(workspace).getByRole("button", { name: "Pin GUI development" }));
    const pinned = screen.getByRole("region", { name: "Pinned" });
    expect(pinned.nextElementSibling).toBe(chats);
    expect(within(pinned).getByRole("button", { name: /^GUI development ·/ })).toBeVisible();
    expect(within(chats).queryByRole("button", { name: /^GUI development ·/ })).toBeNull();
    expect(within(pinned).getByRole("button", { name: "Unpin GUI development" })).toHaveFocus();
    first.unmount();

    const reopened = render(<HarnessGui client={attached("sidebar-a", "host-two")} />);
    const restoredPin = await screen.findByRole("button", { name: "Unpin GUI development" });
    expect(restoredPin).toBeVisible();
    reopened.unmount();

    const other = render(<HarnessGui client={attached("sidebar-b", "host-two")} />);
    await screen.findByRole("button", { name: "Pin GUI development" });
    expect(screen.queryByRole("region", { name: "Pinned" })).toBeNull();
    other.unmount();

    render(<HarnessGui client={attached("sidebar-a", "host-two")} />);
    await user.click(await screen.findByRole("button", { name: "Unpin GUI development" }));
    expect(screen.queryByRole("region", { name: "Pinned" })).toBeNull();
    expect(within(screen.getByRole("region", { name: "Chats" }))
      .getByRole("button", { name: "Pin GUI development" })).toHaveFocus();
  });

  const originalWidth = window.innerWidth;
  afterEach(() => { vi.unstubAllGlobals(); Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth }); });
  it("shares measured content margins including a native scrollbar", async () => {
    let resize = () => {};
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { resize = callback; }
      observe() {}
      disconnect() {}
    });
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });
    const pane = screen.getByLabelText("Session workspace");
    const transcript = screen.getByLabelText("Session transcript");
    Object.defineProperty(pane, "clientWidth", { configurable: true, value: 1140 });
    Object.defineProperty(transcript, "offsetWidth", { configurable: true, value: 1140 });
    Object.defineProperty(transcript, "clientWidth", { configurable: true, value: 1125 });
    act(() => resize());
    expect(pane.style.getPropertyValue("--content-gutter")).toBe("182.5px");
    expect(pane.style.getPropertyValue("--scrollbar-width")).toBe("15px");
  });
  it("reserves right space and changes layout based on remaining width", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });
    const layout = screen.getByRole("main");
    expect(layout).toHaveClass("right-visible");
    expect(layout).not.toHaveClass("right-stacked");
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 });
    fireEvent(window, new Event("resize"));
    expect(layout).toHaveClass("right-stacked");
    await user.click(screen.getByRole("button", { name: "Toggle sidebar" }));
    expect(layout).not.toHaveClass("right-stacked");
    await user.click(screen.getByRole("button", { name: "Toggle environment" }));
    expect(layout).toHaveClass("dock-closed");
    expect(layout).not.toHaveClass("right-visible");
  });
  it("toggles the sidebar with its button and Ctrl+B and retains width", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });
    const separator = screen.getByRole("separator", { name: "Sidebar width" });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(separator).toHaveAttribute("aria-valuenow", "290");
    await user.click(screen.getByRole("button", { name: "Toggle sidebar" }));
    expect(screen.getByLabelText("Workspace and Session navigation")).not.toBeVisible();
    await user.keyboard("{Control>}b{/Control}");
    expect(screen.getByLabelText("Workspace and Session navigation")).toBeVisible();
    expect(separator).toHaveAttribute("aria-valuenow", "290");
    fireEvent.doubleClick(separator);
    expect(separator).toHaveAttribute("aria-valuenow", "280");
    expect(screen.queryByLabelText("Application menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Minimize window" })).not.toBeInTheDocument();
  });

  it("separates environment and work panel controls and shares the Work Dock and switches to Review", async () => {
    const user = userEvent.setup();
    render(<HarnessGui client={createMockAppClient()} />);
    await screen.findByRole("heading", { name: "GUI development" });
    expect(screen.getByLabelText("Environment summary")).toBeVisible();
    expect(screen.queryByLabelText("Work Dock")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bottom panel unavailable" })).toBeDisabled();
    await user.click(within(screen.getByLabelText("Environment summary")).getByRole("button", { name: "Review" }));
    expect(screen.getByLabelText("Read-only review")).toBeVisible();
    expect(screen.queryByLabelText("Environment summary")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Work Dock" }));
    expect(screen.queryByLabelText("Work Dock")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Toggle environment" }));
    expect(screen.getByLabelText("Environment summary")).toBeVisible();
  });

  it("replaces native decorations and grants only scoped window commands", () => {
    expect(config.app.windows[0].decorations).toBe(false);
    expect(capability.windows).toEqual(["main"]);
    for (const action of ["minimize", "toggle-maximize", "close", "start-dragging"]) {
      expect(capability.permissions).toContain(`core:window:allow-${action}`);
    }
  });
});
