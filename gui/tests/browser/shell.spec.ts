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
    const rail = page.getByLabel("Collapsed sidebar", { exact: true });
    await expect(rail).toBeVisible();
    expect((await rail.boundingBox())!.width).toBe(48);
    const avatar = rail.getByRole("button", { name: "Account menu" });
    await expect(avatar).toBeVisible();
    expect((await avatar.boundingBox())!.y).toBeGreaterThan(800);
    await avatar.click();
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "Settings" });
    await expect(settings.getByRole("combobox", { name: "Interface language" })).toHaveValue("system");
    await settings.getByRole("button", { name: "Close settings" }).click();
    await expect(avatar).toBeFocused();
    await page.screenshot({ path: info.outputPath("collapsed-rail.png"), fullPage: true });
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
  // Exercise the desktop fixture shell independently of managed Host startup.
  await page.route(/LocalHostGate\.tsx(?:[?]|$)/, (route) => route.fulfill({
    contentType: "application/javascript",
    body: 'export { default } from "/src/App.tsx";',
  }));
  // DOM acceptance only: these stubs do not establish actual OS window behavior.
  await page.addInitScript(() => {
    Object.assign(window, {
      isTauri: true,
      resizeRequests: [] as unknown[],
      __TAURI_EVENT_PLUGIN_INTERNALS__: { unregisterListener: () => {} },
      __TAURI_INTERNALS__: {
        metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
        transformCallback: () => 1,
        unregisterCallback: () => {},
        invoke: async (command: string, args: unknown) => {
          if (command === "plugin:window|start_resize_dragging") {
            (window as unknown as { resizeRequests: unknown[] }).resizeRequests.push(args);
          }
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
  await page.locator('.window-resize-edge[data-edge="SouthEast"]').click();
  expect(await page.evaluate(() => (window as unknown as { resizeRequests: unknown[] }).resizeRequests)).toEqual([expect.objectContaining({ value: "SouthEast" })]);
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
  await expect(page.getByRole("menuitem", { name: "Open terminal" })).toBeDisabled();
  await expect(page.getByRole("menuitem", { name: "Toggle full screen" })).toBeDisabled();
  await page.screenshot({ path: info.outputPath("desktop-menu.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Documentation" })).toBeDisabled();
  await page.getByRole("menuitem", { name: "About loushang" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "File", exact: true }).click();
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  await page.getByRole("dialog", { name: "Settings" }).getByRole("combobox").selectOption("zh-CN");
  await expect(page.getByRole("dialog", { name: "设置" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("Control+,");
  await expect(page.getByRole("dialog", { name: "设置" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "切换侧边栏" }).click();
  await page.setViewportSize({ width: 1440, height: 720 });
  for (const [label, filename] of [["文件", "file"], ["编辑", "edit"], ["视图", "view"], ["帮助", "help"]]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    const bounds = (await page.getByRole("menu", { name: label }).boundingBox())!;
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(720);
    await page.screenshot({ path: info.outputPath(`menu-${filename}-zh.png`), fullPage: true });
    await page.keyboard.press("Escape");
  }
  expect(errors).toEqual([]);
});

test("composer keeps controls aligned and uses Enter to send at a narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Operational ontology · Idle" }).click();
  const input = page.getByRole("textbox", { name: "Message for Operational ontology" });
  const send = page.getByRole("button", { name: "Send", exact: true });
  const controls = [
    page.getByRole("button", { name: "Attach file unavailable" }),
    page.getByRole("button", { name: "Session model" }),
    send,
  ];
  const centers = await Promise.all(controls.map(async (control) => {
    const box = (await control.boundingBox())!;
    return box.y + box.height / 2;
  }));
  expect(Math.max(...centers) - Math.min(...centers)).toBeLessThan(1);

  await input.fill("First line");
  await input.press("Control+Enter");
  await input.pressSequentially("Second line");
  await expect(input).toHaveValue("First line\nSecond line");
  await expect(send).toBeEnabled();
  await input.press("Enter");
  await expect(input).toHaveValue("");
  await expect(page.getByRole("article", { name: "user message" }).filter({ hasText: "First line Second line" })).toBeVisible();
});
