import { expect, test } from "@playwright/test";

for (const width of [700, 1440]) {
  test(`web omits desktop chrome and can reopen the sidebar at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "GUI development" })).toBeVisible();
    await expect(page.locator(".native-frame")).toHaveCount(0);
    await expect(page.locator(".window-controls")).toHaveCount(0);
    expect((await page.locator("main").boundingBox())!.y).toBe(0);
    await expect(page.locator(".brand-row").getByRole("button", { name: "Toggle sidebar" })).toBeVisible();
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    const reopen = page.getByRole("button", { name: "Toggle sidebar" });
    await expect(reopen).toBeVisible();
    await expect(reopen).toBeFocused();
    await reopen.click();
    await expect(page.getByLabel("Workspace and Session navigation", { exact: true })).toBeVisible();
    await expect(page.locator(".brand-row").getByRole("button", { name: "Toggle sidebar" })).toBeFocused();
    if (width <= 760) await page.getByRole("button", { name: "Toggle sidebar" }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath("web-shell.png"), fullPage: true });
  });
}

test("desktop shell renders menus and Session history with a simulated native bridge", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // DOM acceptance only: these stubs do not establish actual OS window behavior.
  await page.addInitScript(() => {
    Object.assign(window, {
      isTauri: true,
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} },
      __TAURI_INTERNALS__: {
        metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
        transformCallback: () => 1,
        unregisterCallback: () => {},
        invoke: async (command: string) => {
          if (command === "plugin:os|locale") return "en-US";
          if (command === "plugin:event|listen") return 1;
          if (command === "fixture_bridge_handshake") throw new Error("Fixture bridge disabled");
          return false;
        },
      },
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "GUI development" })).toBeVisible();
  await expect(page.locator(".native-frame")).toBeVisible();
  await expect(page.locator(".native-frame").getByRole("button", { name: "Toggle sidebar" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Back", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Operational ontology · Idle" }).click();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByRole("heading", { name: "GUI development" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Forward", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "File", exact: true }).click();
  await page.getByRole("menuitem", { name: "Focus message input" }).click();
  await expect(page.getByRole("textbox")).toBeFocused();
  await page.getByRole("button", { name: "View", exact: true }).click();
  await expect(page.getByRole("menuitemcheckbox", { name: /Toggle sidebar/ })).toBeVisible();
  await page.screenshot({ path: info.outputPath("desktop-menu.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await page.getByRole("menuitem", { name: "About loushang" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});
