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
  const panel = render(<WorkspaceInspection load={load} review revision="" />);
  expect(await screen.findByText(/Restart the local AppHost/)).toBeVisible();
  panel.rerender(<WorkspaceInspection load={load} review revision="" refresh={1} />);
  expect(load).toHaveBeenCalledTimes(2);
});

const git = { root: "/project", branch: "main", commit: "06f8a3f6f764", worktree: "" };

it("distinguishes an empty review, an unavailable baseline and a partial report", async () => {
  const load = vi.fn().mockResolvedValue({ git, changes: [], toolchains: [], limited: false });
  const panel = render(<WorkspaceInspection load={load} review revision="1" />);
  expect(await screen.findByRole("heading", { name: "No changes to review" })).toBeVisible();
  load.mockResolvedValue({ git: null, changes: [], toolchains: [], limited: false });
  panel.rerender(<WorkspaceInspection load={load} review revision="2" />);
  expect(await screen.findByRole("heading", { name: "Review unavailable" })).toBeVisible();
  load.mockResolvedValue({ git, changes: [], toolchains: [], limited: true });
  panel.rerender(<WorkspaceInspection load={load} review revision="3" />);
  expect(await screen.findByText("Only part of the changes could be loaded.")).toBeVisible();
  expect(screen.queryByText("No changes to review")).not.toBeInTheDocument();
  load.mockResolvedValue({ git: null, changes: [], sessionChanges: [], toolchains: [], limited: false });
  panel.rerender(<WorkspaceInspection load={load} review revision="4" />);
  expect(await screen.findByRole("heading", { name: "No changes to review" })).toBeVisible();
  expect(screen.getByText("There are no recorded file changes in this session.")).toBeVisible();
});

it("opens only the selected file's diff", async () => {
  const load = vi.fn().mockResolvedValue({
    git, toolchains: [], limited: false,
    changes: [
      { path: "first file.txt", kind: "unstaged", added: 1, removed: 1 },
      { path: "second.txt", kind: "unstaged", added: 1, removed: 0 },
    ],
    unstagedDiff: [
      "diff --git a/first file.txt b/first file.txt", "--- a/first file.txt", "+++ b/first file.txt",
      "@@ -1 +1 @@", "-before", "+first edit",
      "diff --git a/second.txt b/second.txt", "--- a/second.txt", "+++ b/second.txt",
      "@@ -1,0 +1 @@", "+second edit",
    ].join("\n"),
  });
  render(<WorkspaceInspection load={load} review revision="" />);
  const file = await screen.findByText("first file.txt");
  expect(file.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(file);
  expect(file.closest("details")).toHaveAttribute("open");
  expect(file.closest("details")).toHaveTextContent("+first edit");
  expect(file.closest("details")).not.toHaveTextContent("+second edit");
});

it("reports a failed load separately from empty review and can recover", async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error("connection_failed"))
    .mockResolvedValue({ git, changes: [], toolchains: [], limited: false });
  const panel = render(<WorkspaceInspection load={load} review revision="" />);
  expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  expect(await screen.findByRole("heading", { name: "Could not load review" })).toBeVisible();
  panel.rerender(<WorkspaceInspection load={load} review revision="" refresh={1} />);
  expect(await screen.findByRole("heading", { name: "No changes to review" })).toBeVisible();
});

it("uses the same environment rows for different toolchains and omits a duplicate root", async () => {
  const load = vi.fn().mockResolvedValue({
    git, changes: [], limited: false, toolchains: [
      { name: "Python", declared: ">=3.11", environment: ".venv" },
      { name: "Go", declared: "1.24", detected: "1.24.2" },
    ],
  });
  const panel = render(<WorkspaceInspection load={load} review={false} revision="1" workspacePath="/project" />);
  expect(await screen.findByRole("heading", { name: "Git" })).toBeVisible();
  expect(screen.getByText("No changes to review")).toBeVisible();
  expect(screen.getByText("main")).toBeVisible();
  expect(screen.queryByText("Git repository root")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Python" })).toBeVisible();
  expect(screen.getByText(".venv")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Go" })).toBeVisible();
  expect(screen.getByText("1.24.2")).toBeVisible();

  load.mockResolvedValue({ git: { ...git, root: "/parent", branch: "", worktree: "linked" },
    changes: [{ path: "note", kind: "unstaged", added: 1, removed: 0 }], limited: false,
    toolchains: [{ name: "Java" }] });
  panel.rerender(<WorkspaceInspection load={load} review={false} revision="2" workspacePath="/project" />);
  expect(await screen.findByText("Detached HEAD")).toBeVisible();
  expect(screen.getByText("1 changed file")).toBeVisible();
  expect(screen.getByText("/parent")).toBeVisible();
  expect(screen.getByText("linked")).toBeVisible();
  expect(screen.getByText("Detected version")).toBeVisible();
});

it("keeps session-recorded changes distinct when there is no Git baseline", async () => {
  const load = vi.fn().mockResolvedValue({
    git: null, changes: [], toolchains: [], limited: true,
    sessionChanges: [
      { path: "index.html", created: true, added: null, removed: null },
      { path: "weather.css", created: false, added: 1, removed: 1 },
    ],
    sessionDiff: "--- weather.css\n+++ weather.css\n@@ -1 +1 @@\n-old\n+new\n",
  });
  render(<WorkspaceInspection load={load} review revision="" />);
  expect(await screen.findByRole("heading", { name: "Session file changes" })).toBeVisible();
  expect(screen.getByText("Created")).toBeVisible();
  expect(screen.getByText("Only part of the changes could be loaded.")).toBeVisible();
  const file = screen.getByText("weather.css");
  await userEvent.click(file);
  expect(file.closest("details")).toHaveAttribute("open");
});

it("reports a workspace mismatch and allows reopening the folder", async () => {
  const open = vi.fn().mockRejectedValueOnce(new Error("workspace_unavailable")).mockResolvedValue(undefined);
  render(<OpenWorkspacePath open={open} />);
  const button = screen.getByRole("button", { name: "Open folder" });
  await userEvent.click(button);
  expect(await screen.findByText("This path is no longer registered for the selected session.")).toBeVisible();
  await userEvent.click(button);
  expect(open).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
