import { expect, test, type Page } from "@playwright/test";
import { appName } from "../../src/branding";

const hoverGray = "rgb(236, 236, 235)";
const focusGray = "rgb(104, 108, 114)";

async function simulateDesktop(page: Page, managed = false) {
  await page.addInitScript((managed) => {
    Object.assign(window, {
      isTauri: true,
      __LOUSHANG_MANAGED_TEST__: managed,
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
          if (managed && command === "offline_account") return { name: "desktop-user", id: "local-preview-account" };
          if (managed && command === "client_settings") {
            const { request } = args as { request: { operation: string } };
            if (request.operation === "connections/list") return {
              selectedId: "local",
              connections: [{ id: "local", name: "Local", kind: "local", selected: true, workspace: "/preview" }],
            };
            if (request.operation === "environment") return { supported: true, workspace: "/preview", connectionId: "local" };
            return {
              state: "exited", workspace: "/preview", errorCode: "unclean_exit", pid: 1234,
              instanceId: "host-instance-" + "a".repeat(48), serviceInstanceId: "service-instance-" + "b".repeat(48),
            };
          }
          return false;
        },
      },
    });
  }, managed);
}

for (const width of [700, 1440]) {
  test(`web omits desktop chrome and can reopen the sidebar at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "GUI development" })).toBeVisible();
    await expect(page.locator(".native-frame")).toHaveCount(0);
    await expect(page.locator(".window-controls")).toHaveCount(0);
    expect((await page.locator("main").boundingBox())!.y).toBe(0);
    const reopen = page.getByRole("button", { name: "Toggle sidebar" });
    await expect(reopen).toBeVisible();
    const rail = page.getByLabel("Collapsed sidebar", { exact: true });
    await expect(rail).toBeVisible();
    expect((await rail.boundingBox())!.width).toBe(48);
    const avatar = rail.getByRole("button", { name: "Account menu" });
    await expect(avatar).toBeVisible();
    expect((await avatar.boundingBox())!.y).toBeGreaterThan(800);
    await avatar.hover();
    await expect(avatar).toHaveCSS("background-color", hoverGray);
    await avatar.click();
    const openSettings = page.getByRole("button", { name: "Settings", exact: true });
    await openSettings.hover();
    await expect(openSettings).toHaveCSS("background-color", hoverGray);
    await expect(openSettings).toBeFocused();
    await expect(openSettings).toHaveCSS("outline-style", "none");
    await openSettings.click();
    const settings = page.getByRole("dialog", { name: "Settings" });
    await expect(settings.getByRole("combobox", { name: "Interface language" })).toHaveText("Follow system");
    const general = settings.getByRole("button", { name: "General", exact: true });
    await general.hover();
    await expect(general).toHaveCSS("background-color", hoverGray);
    await settings.getByRole("button", { name: "Close settings" }).click();
    await expect(avatar).toBeFocused();
    await expect(avatar).toHaveCSS("outline-style", "none");
    await page.screenshot({ path: info.outputPath("collapsed-rail.png"), fullPage: true });
    await reopen.click();
    await expect(page.getByLabel("Workspace and Session navigation", { exact: true })).toBeVisible();
    await expect(page.locator(".brand-row").getByRole("button", { name: "Toggle sidebar" })).toBeFocused();
    const accountFooter = page.locator(".rail-footer");
    await accountFooter.hover();
    await expect(accountFooter).toHaveCSS("background-color", hoverGray);
    await accountFooter.press("Enter");
    await expect(openSettings).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(accountFooter).toBeFocused();
    await expect(accountFooter).toHaveCSS("outline-style", "solid");
    await expect(accountFooter).toHaveCSS("outline-color", focusGray);
    await expect(accountFooter).toHaveCSS("outline-offset", "-2px");
    await accountFooter.click();
    await expect(openSettings).toHaveCSS("outline-style", "none");
    await openSettings.click();
    const closeSettings = settings.getByRole("button", { name: "Close settings" });
    await expect(closeSettings).toHaveCSS("outline-style", "none");
    await closeSettings.click();
    await expect(accountFooter).toBeFocused();
    await expect(accountFooter).toHaveCSS("outline-style", "none");
    const navigation = page.getByLabel("Workspace and Session navigation", { exact: true });
    await page.reload();
    await expect(navigation).toBeVisible();
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await expect(reopen).toBeFocused();
    await page.reload();
    await expect(rail).toBeVisible();
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
  await simulateDesktop(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await expect(page.locator(".brand-name")).toHaveText(appName);
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
  const help = page.getByRole("button", { name: "Help", exact: true });
  await help.hover();
  await expect(help).toHaveCSS("background-color", hoverGray);
  await help.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Documentation" })).toBeDisabled();
  const about = page.getByRole("menuitem", { name: `About ${appName}` });
  await about.hover();
  await expect(about).toHaveCSS("background-color", hoverGray);
  await page.keyboard.press("Escape");
  await expect(help).toBeFocused();
  await expect(help).toHaveCSS("outline-color", focusGray);
  await expect(help).toHaveCSS("outline-offset", "-2px");
  await page.screenshot({ path: info.outputPath("help-keyboard-focus.png"), fullPage: true });
  await help.click();
  await about.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "File", exact: true }).click();
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  await page.getByRole("dialog", { name: "Settings" }).getByRole("combobox", { name: "Interface language" }).click();
  await page.getByRole("option", { name: "简体中文" }).click();
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

test("General and Host share a fixed dialog with scrollable content in a short window", async ({ page }, info) => {
  await page.setViewportSize({ width: 680, height: 360 });
  await simulateDesktop(page, true);
  await page.goto("/");
  await page.getByRole("button", { name: "Account menu" }).click();
  const account = page.getByRole("region", { name: "Offline account" });
  await expect(account.getByText("desktop-user")).toBeVisible();
  await expect(account.getByText("local-preview-account")).toBeVisible();
  await page.screenshot({ path: info.outputPath("account-menu.png") });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  const generalBounds = await settings.boundingBox();
  await expect(settings.getByText("local-preview-account")).toHaveCount(0);
  await settings.getByRole("combobox", { name: "Markdown theme" }).click();
  const options = settings.getByRole("listbox", { name: "Markdown theme" });
  const bounds = (await options.boundingBox())!;
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(generalBounds!.y + generalBounds!.height);
  await expect(options.getByRole("option", { name: "Loushang Minimal" })).toBeVisible();
  await settings.getByRole("combobox", { name: "Markdown theme" }).press("Escape");
  await settings.getByRole("button", { name: "Host", exact: true }).click();
  expect(await settings.boundingBox()).toEqual(generalBounds);
  const host = settings.getByRole("region", { name: "Host", exact: true });
  const identity = host.getByRole("region", { name: "Host information" });
  await expect(identity.getByText("1234")).toBeVisible();
  await expect(identity.getByText("Service instance ID")).toBeVisible();
  expect(await host.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await settings.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
  await identity.scrollIntoViewIfNeeded();
  await expect(settings.getByRole("button", { name: "Close settings" })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("host-details.png") });
  await settings.getByRole("button", { name: "General" }).click();
  expect(await settings.boundingBox()).toEqual(generalBounds);
  await page.setViewportSize({ width: 920, height: 700 });
  await settings.getByRole("button", { name: "Host", exact: true }).click();
  await host.evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: info.outputPath("host-settings.png") });
});

test("composer keeps controls aligned and uses Enter to send at a narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
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
