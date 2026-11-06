import { expect, test } from "@playwright/test";

for (const width of [700, 1100, 1440]) {
  test(`language switch preserves work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort());
    await page.goto("/");
    const input = page.getByRole("textbox");
    await input.fill("Draft remains unchanged 世界");
    const menu = page.locator("#interface-language");
    await menu.selectOption("zh-CN");
    await expect(page.getByText("界面语言", { exact: true })).toBeAttached();
    await expect(input).toHaveValue("Draft remains unchanged 世界");
    await expect(page.getByRole("button", { name: "中断", exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    const checkBounds = async () => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const button = page.locator(".composer-submit");
      await button.scrollIntoViewIfNeeded();
      expect(await button.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
      })).toBe(true);
    };
    if (width <= 760) await page.getByRole("button", { name: "切换侧边栏" }).click();
    await checkBounds();
    await page.getByRole("button", { name: "打开工作面板" }).click();
    await checkBounds();
    await page.screenshot({ path: `test-results/layout/i18n-zh-${width}.png`, fullPage: true });
    if (width <= 760) await page.getByRole("button", { name: "切换侧边栏" }).click();
    await menu.selectOption("en-US");
    if (width <= 760) await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await expect(input).toHaveValue("Draft remains unchanged 世界");
    await checkBounds();
    await page.reload();
    await expect(menu).toHaveValue("en-US");
    await menu.selectOption("zh-CN");
    await page.reload();
    await expect(page.getByText("界面语言", { exact: true })).toBeAttached();
  });
}

test("expanded translations keep the primary action reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("textbox")).toBeVisible();
  await page.evaluate(async () => {
    const modulePath = "/src/i18n/index.ts";
    const { i18n } = await import(modulePath);
    function expand(value: unknown): unknown {
      if (typeof value === "string") return /[a-z]/i.test(value.replace(/\{\{.*?\}\}/g, "")) ? `[${value} — ${"long ".repeat(4)}]` : value;
      return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, child]) => [key, expand(child)]));
    }
    for (const namespace of Object.keys(i18n.store.data["en-US"])) {
      i18n.addResourceBundle("en-US", namespace, expand(i18n.getResourceBundle("en-US", namespace)), true, true);
    }
    await i18n.changeLanguage("zh-CN");
    await i18n.changeLanguage("en-US");
  });
  const button = page.locator(".composer-submit");
  await button.scrollIntoViewIfNeeded();
  expect(await button.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
  })).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const pane = (await page.locator(".conversation-pane").boundingBox())!;
  const environment = (await page.locator(".environment-popover").boundingBox())!;
  expect(environment.x).toBeGreaterThanOrEqual(pane.x + pane.width - 1);
  for (const selector of [".composer", ".change-card", ".activity-summary"]) {
    const box = (await page.locator(selector).boundingBox())!;
    expect(box.x + box.width, selector).toBeLessThanOrEqual(pane.x + pane.width + 1);
  }
  await page.screenshot({ path: "test-results/layout/i18n-expanded.png", fullPage: true });
});

for (const [locale, language] of [["zh-CN", "zh-CN"], ["zh-SG", "zh-CN"], ["zh-TW", "en-US"], ["en-GB", "en-US"], ["de-DE", "en-US"]]) {
  test(`startup follows ${locale} as ${language}`, async ({ browser }) => {
    const context = await browser.newContext({ locale });
    try {
      const page = await context.newPage();
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("lang", language);
      await expect(page.locator("#interface-language")).toHaveValue("system");
      await expect(page.getByRole("button", { name: language === "zh-CN" ? "中断" : "Interrupt", exact: true })).toBeEnabled();
      await page.locator("#interface-language").selectOption(language === "zh-CN" ? "en-US" : "zh-CN");
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("lang", language === "zh-CN" ? "en-US" : "zh-CN");
      await page.locator("#interface-language").selectOption("system");
      await expect(page.locator("html")).toHaveAttribute("lang", language);
    } finally { await context.close(); }
  });
}

test("open panels and raw documents survive language changes through complete playback", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const menu = page.locator("#interface-language");
  await page.getByRole("textbox").fill("保留 draft 世界");
  await page.locator(".change-files button").first().click();
  const rawDiff = await page.locator(".quick-look pre").innerText();
  await menu.selectOption("zh-CN");
  await expect(page.getByRole("button", { name: "关闭快速预览" })).toBeVisible();
  await expect(page.locator(".quick-look pre")).toHaveText(rawDiff);
  await page.getByRole("button", { name: "打开完整审阅 →" }).click();
  await expect(page.getByRole("button", { name: "提交或推送" })).toBeDisabled();
  await expect(page.locator(".review-panel pre")).toHaveText(rawDiff);
  await page.locator(".dock-tabs").getByRole("button", { name: "任务", exact: true }).click();
  const taskTitle = await page.locator(".selection-detail h2").innerText();
  await menu.selectOption("en-US");
  await expect(page.locator(".selection-detail h2")).toHaveText(taskTitle);
  await expect(page.getByRole("heading", { name: "Assigned AgentRuns" })).toBeVisible();
  await page.locator(".dock-tabs").getByRole("button", { name: "Subagents" }).click();
  const agentTitle = await page.locator(".selection-detail h2").innerText();
  await menu.selectOption("zh-CN");
  await expect(page.locator(".selection-detail h2")).toHaveText(agentTitle);
  await expect(page.getByRole("heading", { name: "关联任务" })).toBeVisible();
  await page.getByRole("button", { name: "关闭工作面板" }).click();
  await page.locator(".playback-strip summary").click();
  for (let step = 0; step < 11; step++) {
    const chinese = step % 2 === 0;
    await menu.selectOption(chinese ? "zh-CN" : "en-US");
    await page.getByRole("button", { name: chinese ? "推进测试回放" : "Advance fixture", exact: true }).click();
    await expect(page.getByRole("textbox")).toHaveValue("保留 draft 世界");
    expect(await page.locator("body").innerText()).not.toMatch(/\{\{|(?:session|workspace|panels|shell|common):[a-z]/);
  }
  await menu.selectOption("zh-CN");
  await expect(page.getByRole("button", { name: "已完成 4 / 4", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "GUI development · 空闲", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/layout/i18n-full-playback.png", fullPage: true });
  expect(errors).toEqual([]);
});
