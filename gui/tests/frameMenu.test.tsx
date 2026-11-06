import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { FrameMenu } from "../src/FrameMenu";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

it("gates new Session by capability and focuses the composer", async () => {
  const focus = vi.fn();
  const user = userEvent.setup();
  const view = render(<FrameMenu sidebarOpen onToggleSidebar={() => {}} onFocusComposer={focus} />);
  await user.click(screen.getByRole("button", { name: "File" }));
  expect(screen.getByRole("menuitem", { name: "New session" })).toBeDisabled();
  expect(screen.queryByRole("menuitem", { name: "Close window" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("menuitem", { name: "Focus message input" }));
  expect(focus).toHaveBeenCalledOnce();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  const create = vi.fn();
  view.rerender(<FrameMenu sidebarOpen onToggleSidebar={() => {}} onNewSession={create} />);
  await user.click(screen.getByRole("button", { name: "File" }));
  await user.click(screen.getByRole("menuitem", { name: "New session" }));
  expect(create).toHaveBeenCalledOnce();
});

it("supports keyboard navigation, Escape focus return and outside dismissal", async () => {
  const user = userEvent.setup();
  render(<FrameMenu sidebarOpen onToggleSidebar={() => {}} />);
  screen.getByRole("button", { name: "File" }).focus();
  await user.keyboard("{ArrowDown}{ArrowRight}");
  expect(screen.getByRole("menuitem", { name: "Select all" })).toHaveFocus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("menuitemcheckbox", { name: /Toggle sidebar/ })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "View" })).toHaveFocus();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.click(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("toggles view state and opens useful help", async () => {
  const toggle = vi.fn(), environment = vi.fn();
  const user = userEvent.setup();
  render(<FrameMenu sidebarOpen onToggleSidebar={toggle} onToggleEnvironment={environment} />);
  await user.click(screen.getByRole("button", { name: "View" }));
  expect(screen.getByRole("menuitemcheckbox", { name: /Toggle sidebar/ })).toHaveAttribute("aria-checked", "true");
  await user.click(screen.getByRole("menuitemcheckbox", { name: /Toggle sidebar/ }));
  expect(toggle).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "View" }));
  await user.click(screen.getByRole("menuitemcheckbox", { name: "Toggle environment panel" }));
  expect(environment).toHaveBeenCalledOnce();
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.click(screen.getByRole("menuitem", { name: "Keyboard shortcuts" }));
  expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveTextContent("Ctrl+B");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Help" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.click(screen.getByRole("menuitem", { name: "About loushang" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Offline fixture");
});

it("copies the selection captured before the menu takes focus and reports denial", async () => {
  const user = userEvent.setup();
  const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  render(<><textarea defaultValue="keep this draft" aria-label="Draft" /><FrameMenu sidebarOpen onToggleSidebar={() => {}} /></>);
  const draft = screen.getByRole("textbox") as HTMLTextAreaElement;
  draft.focus(); draft.setSelectionRange(5, 9);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("menuitem", { name: "Copy selection" }));
  expect(write).toHaveBeenCalledWith("this");
  write.mockRejectedValueOnce(new Error("denied"));
  draft.focus(); draft.setSelectionRange(5, 9);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("menuitem", { name: "Copy selection" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not copy");
  expect(draft.value).toBe("keep this draft");
});

it("selects the draft without changing it", async () => {
  const user = userEvent.setup();
  render(<><textarea defaultValue="draft" /><FrameMenu sidebarOpen onToggleSidebar={() => {}} /></>);
  const draft = screen.getByRole("textbox") as HTMLTextAreaElement;
  draft.focus(); fireEvent.select(draft, { target: { selectionStart: 1, selectionEnd: 2 } });
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("menuitem", { name: "Select all" }));
  await waitFor(() => expect(draft).toHaveFocus());
  expect([draft.selectionStart, draft.selectionEnd]).toEqual([0, 5]);
});
