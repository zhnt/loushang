import { expect, test } from "@playwright/test";

test("manages folders in one logical workspace without disabling its chat entry", async ({ page }) => {
  await page.addInitScript(() => Object.assign(window, { __LOUSHANG_MANAGED_TEST__: true }));
  const id = "a".repeat(32);
  const paths = [{ id: "front", alias: "frontend", path: "/projects/frontend", status: "missing" }];
  let name = "";
  let defaultPathId: string | null = null;
  const edits: string[] = [];
  await page.route("**/api/loushang", async (route) => {
    const input = route.request().postDataJSON();
    let result: object = {};
    if (input.operation === "environment") result = { supported: true, workspace: "" };
    else if (input.operation === "manage") result = { state: "running", serviceInstanceId: "test-host" };
    else if (input.action === "navigation") result = {
      projects: name ? [{ id, name, path: null, paths, defaultPathId, sessions: [] }] : [],
      temporarySessions: [],
    };
    else if (input.action === "create-workspace") name = input.name;
    else if (input.action === "add-path") {
      expect(input.workspaceId).toBe(id);
      expect(input.path).toBe("/elsewhere/backend");
      paths.push({ id: "back", alias: input.alias, path: input.path, status: "available" });
      edits.push(input.action);
    } else if (input.action === "set-default-path") {
      expect(input.workspaceId).toBe(id);
      expect(input.pathId).toBe("back");
      defaultPathId = input.pathId;
      edits.push(input.action);
    }
    return route.fulfill({ json: { result } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  const projects = page.getByRole("region", { name: "Projects" });
  await expect(projects.getByRole("button", { name: "Create workspace", exact: true })).toHaveCount(0);
  await projects.getByRole("heading", { name: "Projects" }).click({ button: "right" });
  await expect(page.getByRole("menuitem", { name: "Add project" })).toBeVisible();
  await page.getByRole("menuitem", { name: "Create workspace", exact: true }).click();
  let editor = page.getByRole("dialog", { name: "Create workspace" });
  await editor.getByLabel("Workspace name").fill("Integration");
  await editor.getByRole("button", { name: "Create workspace" }).click();
  await expect(editor).toBeHidden();
  const projectChat = page.getByRole("button", { name: "New chat in Integration" });
  await expect(projectChat).toBeEnabled();
  const projectRow = page.getByRole("button", { name: "Integration", exact: true });
  await projectRow.press("Shift+F10");
  await page.getByRole("menuitem", { name: "Manage workspace", exact: true }).click();
  editor = page.getByRole("dialog", { name: "Manage workspace" });
  await expect(editor.getByText("Folder not found")).toBeVisible();
  const close = editor.getByRole("button", { name: "Close" });
  const restingBackground = await close.evaluate((button) => getComputedStyle(button).backgroundColor);
  await close.hover();
  await expect(close).toHaveCSS("border-radius", "6px");
  await expect(close).not.toHaveCSS("background-color", restingBackground);
  await expect(close).toHaveCSS("outline-style", "none");
  await expect(page.locator(".desktop-shell")).toHaveAttribute("data-input-modality", "pointer");
  await editor.getByRole("button", { name: "Add folder", exact: true }).click();
  await editor.getByLabel("Alias").fill("backend");
  await editor.getByLabel("Folder path on the AppHost").fill("/elsewhere/backend");
  await editor.getByRole("button", { name: "Add folder", exact: true }).last().click();
  await editor.getByRole("button", { name: "Actions for backend" }).click();
  await editor.getByRole("menuitem", { name: "Set as default" }).click();
  await expect(editor.getByRole("listitem").filter({ hasText: "backend" }).getByText("Default folder", { exact: true })).toBeVisible();
  await editor.screenshot({ path: test.info().outputPath("workspace-dialog.png") });
  await close.click();
  await expect(projectRow).toBeFocused();
  await expect(projectRow).toHaveCSS("outline-style", "none");
  await page.keyboard.press("Tab");
  await expect(projectChat).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(projectRow).toHaveCSS("outline-style", "solid");
  await page.getByRole("button", { name: "Integration", exact: true }).hover();
  await projects.screenshot({ path: test.info().outputPath("projects.png") });
  await projectChat.click();
  await expect(page.getByRole("heading", { name: "Integration / New Session" })).toBeVisible();
  expect(edits).toEqual(["add-path", "set-default-path"]);
});
