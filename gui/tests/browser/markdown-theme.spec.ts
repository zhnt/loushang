import { expect, test, type Page } from "@playwright/test";

const columns = ["Workspace", "Session", "Runtime", "Model", "Access", "Result", "Notes", "Updated"];
const longPrompt = "请用中文介绍北京的四季气候和出行建议。".repeat(7);
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
  await page.route(/\/tests\/support\/mockAppClient\.ts$/, (route) => route.fulfill({
    contentType: "text/javascript",
    body: `
      import { createMockAppClient as original } from "/tests/support/mockAppClient.ts?markdown-sample";
      export function createMockAppClient() {
        const client = original();
        const snapshot = client.snapshot.bind(client);
        const models = {
          currentId: "preview",
          models: [{ id: "preview", provider: "preview", endpointId: "local", modelId: "sample-model", label: "Sample model", supportsThinking: true }],
          thinking: { currentLevel: "medium", availableLevels: ["low", "medium"] },
        };
        client.sessionModels = async () => models;
        client.selectModel = async () => models;
        client.snapshot = async () => {
          const value = await snapshot();
          return {
            ...value,
            connection: "connected",
            source: { kind: "live", muxSpaceId: "preview-mux", serviceInstanceId: "preview-host", connectionEpoch: "1" },
            sessions: value.sessions.map((session) => session.id === value.selectedSessionId ? {
              ...session,
              status: "idle",
              run: null,
              changeSet: null,
              messages: [
                { id: "preview-short", role: "user", content: "介绍北京天气", phase: "complete" },
                { id: "preview-long", role: "user", content: ${JSON.stringify(longPrompt)}, phase: "complete" },
                ...session.messages.filter((message) => message.role === "assistant").map((message) => ({
                  ...message, content: ${JSON.stringify(markdown)}, phase: "complete",
                })),
              ],
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

test("app appearance includes the shell, settings, and Markdown while preserving the reading layout", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await showSample(page);
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "Toggle environment" }).click();
  const body = page.locator(".markdown-body");
  const reading = page.locator(".markdown-reading");
  const composer = page.locator(".composer");
  const pane = page.locator(".conversation-pane");
  const sidebar = page.locator(".session-rail");
  const input = composer.getByRole("textbox");
  const model = composer.getByRole("button", { name: "Session model" });
  await expect(pane).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(reading).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  const border = await composer.evaluate((element) => getComputedStyle(element).borderColor);
  await input.click();
  await expect(input).toBeFocused();
  await expect(composer).toHaveCSS("border-color", border);
  await expect(model).toBeEnabled();
  await expect(model).toHaveCSS("font-weight", "600");
  await expect(model.locator("[data-icon=chevron-down]")).toBeVisible();
  await model.click();
  await expect(page.getByRole("menuitemradio", { name: /sample-model/ })).toBeChecked();
  await page.keyboard.press("Escape");
  const shortBubble = page.getByRole("article", { name: "user message" }).filter({
    has: page.getByText("介绍北京天气", { exact: true }),
  });
  const longBubble = page.getByRole("article", { name: "user message" }).filter({ hasText: longPrompt });
  const [shortBox, longBox, composerBox] = await Promise.all([shortBubble.boundingBox(), longBubble.boundingBox(), composer.boundingBox()]);
  expect(shortBox!.width).toBeLessThan(200);
  expect(longBox!.width).toBeLessThanOrEqual(composerBox!.width * 0.74 + 1);
  expect(longBox!.height).toBeGreaterThan(shortBox!.height);
  for (const box of [shortBox!, longBox!]) {
    expect(Math.abs(box.x + box.width - (composerBox!.x + composerBox!.width))).toBeLessThanOrEqual(1);
  }
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
  const appearance = settings.getByRole("combobox", { name: "Appearance", exact: true });
  const options = settings.getByRole("listbox", { name: "Appearance" });
  async function selectAppearance(name: string) {
    await appearance.click();
    await options.getByRole("option", { name, exact: true }).click();
  }
  await expect(theme).toHaveText("Loushang Minimal");
  await expect(appearance).toHaveText("Follow system");
  await appearance.click();
  await expect(options.getByRole("option", { name: "Follow system", selected: true })).toBeVisible();
  await expect(appearance).toHaveCSS("outline-style", "none");
  expect(await options.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
  await page.screenshot({ path: info.outputPath("appearance-dropdown.png"), fullPage: true });
  await appearance.press("Escape");
  await expect(options).toHaveCount(0);
  await expect(settings).toBeVisible();
  await appearance.press("ArrowDown");
  await appearance.press("End");
  await appearance.press("Enter");
  await expect(settings).toHaveCSS("background-color", "rgb(32, 32, 31)");
  await expect(theme).toHaveText("Loushang Minimal");
  await page.screenshot({ path: info.outputPath("dark-settings.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(reading).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(pane).toHaveCSS("background-color", "rgb(32, 32, 31)");
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await expect(composer).toHaveCSS("background-color", "rgb(32, 32, 31)");
  await expect(sidebar).toHaveCSS("background-color", "rgb(37, 37, 37)");
  await page.reload();
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await openSettings(page);
  await expect(appearance).toHaveText("Dark");
  await selectAppearance("Follow system");
  await page.keyboard.press("Escape");
  await expect(body).toHaveCSS("color", "rgb(36, 36, 36)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
  await openSettings(page);
  await selectAppearance("Light");
  await expect(body).toHaveCSS("color", "rgb(36, 36, 36)");
  await selectAppearance("Follow system");
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

  await page.evaluate(() => {
    localStorage.removeItem("loushang.gui.appearance");
    localStorage.setItem("loushang.gui.markdown", '{"theme":"removed","scheme":"light"}');
  });
  await page.reload();
  await expect(reading).toHaveAttribute("data-markdown-theme", "loushang-minimal");
  await expect(page.locator("html")).toHaveAttribute("data-appearance", "system");
  await expect(body).toHaveCSS("color", "rgb(237, 237, 235)");
});
