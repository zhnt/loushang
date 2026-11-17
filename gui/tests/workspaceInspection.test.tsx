import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { OpenWorkspacePath, WorkspaceInspection } from "../src/WorkspaceInspection";

it("offers an accessible folder action and explains a missing path", async () => {
  const open = vi.fn().mockRejectedValue("not_found");
  render(<OpenWorkspacePath open={open} />);
  await userEvent.tab();
  expect(screen.getByRole("button", { name: "Open folder" })).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(open).toHaveBeenCalledWith(undefined);
  expect(await screen.findByText("This workspace path no longer exists.")).toBeVisible();
});

it("gives upgrade recovery guidance when AppHost cannot provide review", async () => {
  const load = vi.fn().mockRejectedValue("workspace_inspection_unavailable");
  render(<WorkspaceInspection load={load} review revision="" />);
  expect(await screen.findByText(/Restart the local AppHost/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(load).toHaveBeenCalledTimes(2);
});
