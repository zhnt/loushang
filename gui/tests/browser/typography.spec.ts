import { writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

async function fontsFor(page: Page, selectors: readonly string[]) {
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument");
    return await Promise.all(selectors.map(async (selector) => {
      const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
      const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
      return { selector, fonts };
    }));
  } finally {
    await cdp.detach();
  }
}

for (const sample of [
  { locale: "zh-CN", colorScheme: "dark", width: 1080, scale: 1.25 },
  { locale: "en-US", colorScheme: "light", width: 1440, scale: 1.5 },
] as const) {
  test(`typography for ${sample.locale} at ${sample.scale * 100}% scale`, async ({ browser }, info) => {
    const context = await browser.newContext({
      locale: sample.locale, colorScheme: sample.colorScheme, deviceScaleFactor: sample.scale,
      viewport: { width: sample.width, height: 860 },
    });
    try {
      const page = await context.newPage();
      const fontRequests: string[] = [];
      page.on("request", (request) => { if (request.resourceType() === "font") fontRequests.push(request.url()); });
      await page.route(/\/tests\/browser\/main\.tsx(?:\?.*)?$/, (route) => route.fulfill({
        contentType: "application/javascript",
        body: 'import "/tests/browser/typography.fixture.tsx";',
      }));
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("lang", sample.locale);
      await page.locator(".collapsed-rail .frame-icon").click();
      const labels = page.locator(".project-chat-title");
      const zh = labels.filter({ hasText: /^你好$/ });
      const en = labels.filter({ hasText: /^New Session review$/ });
      const mixed = labels.filter({ hasText: /^项目排版 GUI Review$/ });
      await expect(mixed).toBeVisible();
      await expect(page.locator(".model-trigger")).toContainText("Desktop 文案");
      await expect(page.locator(".markdown-body")).toContainText("中文与 English 混排");
      const cases = ["你好", "New Session review", "项目排版 GUI Review"];
      for (const [index, label] of [zh, en, mixed].entries()) {
        await expect(label).toHaveText(cases[index]);
        await label.evaluate((node, key) => node.setAttribute("data-font-sample", key), `chat-${index}`);
      }
      const selectors = ['[data-font-sample="chat-0"]', '[data-font-sample="chat-1"]',
        '[data-font-sample="chat-2"]', ".project-label span", ".project-navigation .section-label",
        ".session-heading h1", ".model-current-label", ".message.user > p",
        ".markdown-body > p", ".markdown-body pre code"];
      const actualFonts = await fontsFor(page, selectors);
      for (const result of actualFonts) {
        expect(result.fonts.some((font) => font.glyphCount > 0), result.selector).toBe(true);
      }
      const userText = page.locator(".message.user > p");
      const assistantText = page.locator(".markdown-body > p").first();
      await expect(assistantText).toHaveText((await userText.textContent())!);
      const textStyles = (element: Element) => {
        const style = getComputedStyle(element);
        return [style.fontFamily, style.fontSize, style.fontWeight, style.lineHeight, style.color];
      };
      expect(await assistantText.evaluate(textStyles)).toEqual(await userText.evaluate(textStyles));
      const renderedFonts = (selector: string) => actualFonts.find((result) => result.selector === selector)!
        .fonts.filter((font) => font.glyphCount > 0).map((font) => font.postScriptName).sort();
      expect(renderedFonts(".markdown-body > p")).toEqual(renderedFonts(".message.user > p"));
      const report = info.outputPath("rendered-fonts.json");
      await writeFile(report, JSON.stringify(actualFonts, null, 2));
      await info.attach("rendered-fonts", { path: report, contentType: "application/json" });
      await page.screenshot({ path: info.outputPath("sidebar-and-markdown.png"), fullPage: true });

      for (const label of [zh, en, mixed]) {
        await expect(label).toHaveCSS("font-size", "13px");
        await expect(label).toHaveCSS("font-weight", "400");
        await expect(label).toHaveCSS("line-height", "20px");
      }
      await expect(page.locator(".project-label")).toHaveCSS("font-weight", "500");
      await expect(page.locator(".environment-technical dd code").first()).toHaveText("typography");
      const rows = await Promise.all([zh, en, mixed].map((label) => label.boundingBox()));
      expect(new Set(rows.map((row) => row?.height)).size).toBe(1);
      const section = page.locator(".project-navigation .section-label").first();
      await expect(section).toHaveCSS("letter-spacing", "normal");
      await expect(section).toHaveCSS("text-transform", "none");
      const selectedRow = page.locator(".project-navigation .session-row.selected");
      const selectedTitle = selectedRow.locator(".project-chat-title");
      const pin = selectedRow.locator(".session-pin");
      const projectRow = page.locator(".project-row");
      const projectAction = projectRow.locator(".project-action");
      await expect(projectRow).toHaveCSS("height", await selectedRow.evaluate((row) => getComputedStyle(row).height));
      await page.mouse.move(sample.width - 10, 10);
      await expect(pin).toHaveCSS("opacity", "0");
      await expect(projectAction).toHaveCSS("opacity", "0");
      await projectRow.hover();
      await expect(projectAction).toHaveCSS("opacity", "1");
      await expect(pin).toHaveCSS("opacity", "0");
      const selectedBackground = await selectedRow.evaluate((element) => getComputedStyle(element).backgroundColor);
      const titleBeforeHover = await selectedTitle.boundingBox();
      await selectedRow.hover();
      expect(await selectedTitle.boundingBox()).toEqual(titleBeforeHover);
      await expect(selectedRow).toHaveCSS("background-color", selectedBackground);
      await expect(selectedTitle).toHaveCSS("font-weight", "400");
      await expect(pin).toHaveCSS("opacity", "1");
      await selectedRow.locator(".project-chat").focus();
      await page.keyboard.press("Tab");
      await expect(pin).toBeFocused();
      await page.mouse.move(sample.width - 10, 10);
      await expect(pin).toHaveCSS("opacity", "1");
      await selectedTitle.hover();
      await expect(page.locator(".app-tooltip")).toHaveCount(0);
      const themedSurface = page.locator(".conversation-pane");
      const systemBackground = await themedSurface.evaluate((pane) => getComputedStyle(pane).backgroundColor);
      await page.locator("html").evaluate((root, appearance) => root.setAttribute("data-appearance", appearance),
        sample.colorScheme === "dark" ? "light" : "dark");
      const appBackground = await themedSurface.evaluate((pane) => getComputedStyle(pane).backgroundColor);
      expect(appBackground).not.toBe(systemBackground);
      for (const label of await labels.filter({ hasText: /这是用于验证|A long English/ }).all()) {
        await expect(label).toHaveCSS("text-overflow", "ellipsis");
        expect(await label.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
        await expect(label.locator("..")).not.toHaveAttribute("title");
        await label.hover();
        const tooltip = page.locator(".app-tooltip");
        await expect(tooltip).toBeVisible();
        await expect(tooltip).toHaveText((await label.textContent())!);
        await expect(tooltip).toHaveCSS("background-color", appBackground);
      }
      await page.locator("html").evaluate((root) => root.removeAttribute("data-appearance"));
      const input = page.locator("#message-input");
      await input.fill("Mixed 中文 125");
      await expect(input).toHaveValue("Mixed 中文 125");
      await expect(input).toHaveCSS("font-size", "14px");

      await page.locator(".rail-footer").click();
      await page.locator(".account-popover button").click();
      const settings = page.getByRole("dialog");
      await expect(settings).toBeVisible();
      await expect(settings.locator(".settings-preference label").first()).toHaveCSS("font-weight", "500");
      await page.screenshot({ path: info.outputPath("settings.png") });
      await settings.locator(".settings-header button").click();

      await page.setViewportSize({ width: 680, height: 740 });
      await page.addStyleTag({ content: ':root { --font-ui: "Unavailable Loushang Test Family", system-ui, sans-serif; }' });
      await expect(zh).toHaveCSS("font-family", '"Unavailable Loushang Test Family", system-ui, sans-serif');
      const fallbackFonts = await fontsFor(page, selectors.slice(0, 3));
      for (const result of fallbackFonts) expect(result.fonts.some((font) => font.glyphCount > 0)).toBe(true);
      await writeFile(info.outputPath("fallback-fonts.json"), JSON.stringify(fallbackFonts, null, 2));
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(680);
      expect(fontRequests).toEqual([]);
      await page.locator(".brand-actions .frame-icon").click();
      const actions = page.getByRole("button", { name: sample.locale === "zh-CN" ? "会话操作" : "Session actions" });
      await page.locator("html").evaluate((root, appearance) => root.setAttribute("data-appearance", appearance),
        sample.colorScheme === "dark" ? "light" : "dark");
      await actions.hover();
      const hint = page.locator(".app-tooltip");
      await expect(actions).not.toHaveAttribute("title");
      await expect(hint).toHaveText(sample.locale === "zh-CN" ? "会话操作" : "Session actions");
      await expect(hint).toHaveCSS("background-color", await themedSurface.evaluate((element) => getComputedStyle(element).backgroundColor));
      const hintBox = (await hint.boundingBox())!;
      expect(hintBox.y).toBeGreaterThanOrEqual(0);
      expect(hintBox.y + hintBox.height).toBeLessThanOrEqual(740);
      await page.keyboard.press("Escape");
      await expect(hint).toHaveCount(0);
      const send = page.locator(".composer-submit");
      await expect(send).toBeEnabled();
      await send.hover();
      await expect(hint).toHaveText((await send.getAttribute("data-tooltip"))!);
      await page.mouse.move(10, 200);
      await input.focus();
      await page.keyboard.press("Tab");
      await expect(actions).toBeFocused();
      await expect(hint).toHaveText((await actions.getAttribute("data-tooltip"))!);
      await page.locator("html").evaluate((root) => root.removeAttribute("data-appearance"));
      await actions.click();
      const add = page.getByRole("group", { name: sample.locale === "zh-CN" ? "添加" : "Add", exact: true });
      await expect(add.getByRole("menuitem")).toHaveCount(2);
      const mode = page.getByRole("group", { name: sample.locale === "zh-CN" ? "模式" : "Mode", exact: true });
      const goal = mode.getByRole("menuitem", { name: sample.locale === "zh-CN" ? "目标" : "Goal", exact: true });
      const popup = mode.locator("..");
      const popupBox = (await popup.boundingBox())!;
      const actionsBox = (await actions.boundingBox())!;
      expect(popupBox.y + popupBox.height).toBeLessThan(actionsBox.y);
      await popup.screenshot({ path: info.outputPath("session-actions.png") });
      await expect(add.getByRole("menuitem").first()).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      await expect(goal).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.locator(".interactive-goal")).toBeInViewport();

      await page.locator(".composer input[type=file]").setInputFiles([
        { name: "tauri.conf.json", mimeType: "text/plain", buffer: Buffer.from("{}") },
        { name: "preview.png", mimeType: "image/png", buffer: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jCx0AAAAASUVORK5CYII=", "base64",
        ) },
      ]);
      await actions.click();
      await page.getByRole("menuitem", { name: sample.locale === "zh-CN" ? "文件夹" : "Folder", exact: true }).click();
      const tiles = page.locator(".composer-attachment");
      await expect(tiles).toHaveCount(3);
      const boxes = await tiles.evaluateAll((items) => items.map((item) => {
        const { width, height, y } = item.getBoundingClientRect();
        return { width, height, y };
      }));
      expect(boxes).toEqual(Array(3).fill({ width: 64, height: 64, y: boxes[0].y }));
      const remove = tiles.first().locator(".attachment-remove");
      await expect(remove).toHaveCSS("opacity", "0");
      await tiles.first().hover();
      await expect(remove).toHaveCSS("opacity", "1");
      const tileBox = (await tiles.first().boundingBox())!;
      const removeBox = (await remove.boundingBox())!;
      expect(removeBox.x).toBeGreaterThan(tileBox.x + tileBox.width / 2);
      expect(removeBox.y).toBeLessThan(tileBox.y + tileBox.height / 2);
      await page.locator(".composer .attachment-list").screenshot({ path: info.outputPath("draft-attachments.png") });
      await remove.click();
      await expect(tiles).toHaveCount(2);
    } finally {
      await context.close();
    }
  });
}
