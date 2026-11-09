import { expect, test, type Page } from "@playwright/test";

const columns = ["Workspace", "Session", "Runtime", "Model", "Access", "Result", "Notes", "Updated"];
const markdown = [
  "# 阅读主题预览",
  "",
  "正文包含 **中英文混排**、`inline code` 和 [参考链接](https://example.com/)。",
  "",
  "## 表格与代码",
  "",
  "> 引用使用柔和的底色与左侧分隔线。",
  "",
  `| ${columns.join(" | ")} |`,
  `| ${columns.map(() => "---").join(" | ")} |`,
  "| Loushang | Markdown | AppHost | Python | Local | Success | Preview | Today |",
  "",
  "```python",
  "def format_reading_sample():",
  `    return "${"a long code line ".repeat(10)}"`,
  "```",
  "",
  "### 阅读说明",
  "",
  "- 列表项有独立的行间距。",
  "- 输入框上方保留可滚动的留白。",
].join("\n");

async function showSample(page: Page) {
  // Supply a rich reply through the browser fixture client, without a model call.
  await page.route(/\/src\/client\/mockAppClient\.ts$/, (route) => route.fulfill({
    contentType: "text/javascript",
    body: `
      import { createMockAppClient as original } from "/src/client/mockAppClient.ts?markdown-sample";
      export function createMockAppClient() {
        const client = original();
        const snapshot = client.snapshot.bind(client);
        client.snapshot = async () => {
          const value = await snapshot();
          return {
            ...value,
            sessions: value.sessions.map((session) => session.id === value.selectedSessionId ? {
              ...session,
              run: null,
              changeSet: null,
              messages: session.messages.map((message) => message.role === "assistant"
                ? { ...message, content: ${JSON.stringify(markdown)}, phase: "complete" }
                : message),
            } : session),
          };
        };
        return client;
      }
    `,
  }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "阅读主题预览" })).toBeVisible();
}

async function openSettings(page: Page) {
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  return page.getByRole("dialog", { name: "Settings", exact: true });
}

test("Markdown preferences persist, honor system appearance, and stay within the reading surface", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await showSample(page);
  await page.getByRole("button", { name: "Toggle environment" }).click();
  const body = page.locator(".markdown-body");
  const reading = page.locator(".markdown-reading");
  const composer = page.locator(".composer");
  const composerBackground = await composer.evaluate((element) => getComputedStyle(element).backgroundColor);
  const sidebar = page.locator(".session-rail");
  const sidebarBackground = await sidebar.evaluate((element) => getComputedStyle(element).backgroundColor);
  await expect(body).toHaveCSS("color", "rgb(36, 36, 36)");
  await expect(body).toHaveCSS("font-size", "15px");
  await expect(body.getByRole("heading", { level: 1 })).toHaveCSS("font-size", "22px");
  await expect(body.getByRole("heading", { level: 2 })).toHaveCSS("margin-block-start", "24px");
  await expect(body.getByRole("columnheader").first()).toHaveCSS("background-color", "rgb(245, 245, 244)");
  await expect(body.locator("pre")).toHaveCSS("font-size", "13.5px");
  await expect(reading).toHaveCSS("padding-bottom", "40px");
  expect((await body.boundingBox())!.width).toBeCloseTo(760, 0);
  await reading.evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: info.outputPath("loushang-minimal-light.png"), fullPage: true });

  const settings = await openSettings(page);
  const theme = settings.getByRole("combobox", { name: "Markdown theme" });
  const appearance = settings.getByRole("combobox", { name: "Markdown appearance" });
  await expect(theme).toHaveValue("loushang-minimal");
  await expect(appearance).toHaveValue("system");
  await appearance.selectOption("dark");
  await page.keyboard.press("Escape");
  await expect(reading).toHaveCSS("background-color", "rgb(25, 25, 24)");
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await expect(composer).toHaveCSS("background-color", composerBackground);
  await expect(sidebar).toHaveCSS("background-color", sidebarBackground);
  await page.reload();
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await openSettings(page);
  await expect(appearance).toHaveValue("dark");
  await appearance.selectOption("system");
  await page.keyboard.press("Escape");
  await expect(body).toHaveCSS("color", "rgb(36, 36, 36)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await openSettings(page);
  await appearance.selectOption("light");
  await expect(body).toHaveCSS("color", "rgb(36, 36, 36)");
  await appearance.selectOption("system");
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 700, height: 900 });
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "Toggle environment" }).click();
  for (const block of [body.locator(".markdown-table"), body.locator("pre")]) {
    expect(await block.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    await block.evaluate((element) => { element.scrollLeft = 64; });
    expect(await block.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
    await block.evaluate((element) => { element.scrollLeft = 0; });
  }
  expect(await reading.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await reading.evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: info.outputPath("loushang-minimal-dark-narrow.png"), fullPage: true });

  await page.evaluate(() => localStorage.setItem("loushang.gui.markdown", '{"theme":"removed","scheme":"unknown"}'));
  await page.reload();
  await expect(reading).toHaveAttribute("data-markdown-theme", "loushang-minimal");
  await expect(reading).toHaveAttribute("data-markdown-scheme", "system");
});
