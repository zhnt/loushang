import { expect, test, type Page, type TestInfo } from "@playwright/test";

const scenarios = [
  { name: "wide", width: 1730, height: 820, rail: 280, scale: 1 },
  { name: "default", width: 1440, height: 720, rail: 280, scale: 1 },
  { name: "reported-overlap", width: 1240, height: 720, rail: 280, scale: 1 },
  { name: "wide-sidebar", width: 1240, height: 720, rail: 420, scale: 1 },
  { name: "compact", width: 900, height: 720, rail: 280, scale: 1 },
  { name: "sidebar-hidden", width: 900, height: 720, rail: 0, scale: 1 },
  { name: "narrow", width: 700, height: 720, rail: 0, scale: 1 },
  { name: "density-125", width: 1440, height: 720, rail: 280, scale: 1.25 },
  { name: "density-150", width: 1440, height: 720, rail: 280, scale: 1.5 },
];

async function verifyLayout(page: Page, info: TestInfo, mode: string) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const geometry = await page.evaluate(() => {
    function rect(selector: string) {
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Missing layout element: ${selector}`);
      const box = element.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width };
    }
    return {
      composer: rect(".composer"), transcript: rect(".transcript"),
      message: rect(".message.assistant"), changes: rect(".change-card"),
      playback: rect(".playback-strip"), pane: rect(".conversation-pane"),
      right: document.querySelector(".environment-popover, .work-dock") ? rect(".environment-popover, .work-dock") : null,
      stacked: document.querySelector("main")!.classList.contains("right-stacked"),
      viewport: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
    };
  });
  await info.attach(`${mode}-geometry`, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  await page.screenshot({ path: info.outputPath(`${mode}.png`), fullPage: true });
  await info.attach(`${mode}-screenshot`, { path: info.outputPath(`${mode}.png`), contentType: "image/png" });
  for (const item of [geometry.message, geometry.changes, geometry.playback]) {
    expect(Math.abs(item.left - geometry.composer.left), `${mode}: left edges`).toBeLessThanOrEqual(1);
    expect(Math.abs(item.right - geometry.composer.right), `${mode}: right edges`).toBeLessThanOrEqual(1);
  }
  expect(geometry.overflow, `${mode}: horizontal overflow`).toBe(false);
  expect(geometry.composer.right).toBeLessThanOrEqual(geometry.viewport + 1);
  expect(geometry.transcript.bottom).toBeLessThanOrEqual(geometry.playback.top + 1);
  expect(geometry.playback.bottom).toBeLessThanOrEqual(geometry.composer.top + 1);
  if (geometry.right) {
    if (geometry.stacked) expect(geometry.right.top).toBeGreaterThanOrEqual(geometry.pane.bottom - 1);
    else expect(geometry.right.left).toBeGreaterThanOrEqual(geometry.pane.right - 1);
  }
  // Hit-test the action, not merely its bounding box: an overlay must not eat clicks.
  const action = page.getByRole("button", { name: "Interrupt", exact: true });
  await action.scrollIntoViewIfNeeded();
  expect(await action.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
  })).toBe(true);
}

for (const scenario of scenarios) {
  test(scenario.name, async ({ browser }, info) => {
    const context = await browser.newContext({
      viewport: { width: scenario.width, height: scenario.height },
      deviceScaleFactor: scenario.scale, reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    // Fixture playback must not silently depend on a remote server or provider.
    await page.route("**/*", (route) => {
      const host = new URL(route.request().url()).hostname;
      return host === "127.0.0.1" ? route.continue() : route.abort();
    });
    try {
      await page.goto("http://127.0.0.1:1421");
      await expect(page.getByRole("heading", { name: "GUI development" })).toBeVisible();
      if (!scenario.rail) await page.getByRole("button", { name: "Toggle sidebar" }).click();
      else if (scenario.rail !== 280) {
        const separator = page.getByRole("separator", { name: "Sidebar width" });
        const box = (await separator.boundingBox())!;
        await page.mouse.move(box.x + box.width / 2, box.y + 80);
        await page.mouse.down();
        await page.mouse.move(box.x + box.width / 2 + scenario.rail - 280, box.y + 80, { steps: 5 });
        await page.mouse.up();
        await expect(separator).toHaveAttribute("aria-valuenow", String(scenario.rail));
      }
      await verifyLayout(page, info, "environment");
      await page.getByRole("button", { name: "Toggle environment" }).click();
      await verifyLayout(page, info, "closed");
      await page.getByRole("button", { name: "Open Work Dock" }).click();
      await verifyLayout(page, info, "work-panel");
      await page.getByRole("button", { name: "Toggle environment" }).click();
      await expect(page.getByLabel("Work Dock", { exact: true })).toHaveCount(0);
      await verifyLayout(page, info, "environment-restored");
      expect(errors).toEqual([]);
    } finally {
      await context.close();
    }
  });
}
