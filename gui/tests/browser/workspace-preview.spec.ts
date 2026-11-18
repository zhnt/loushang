import { expect, test } from "@playwright/test";
import { liveSnapshot } from "../support/liveSnapshot";

const rootText = "# 当前工作区\n\n[GUI 说明](gui/README.md) · [外部站点](https://example.com)";
const guiText = "# GUI 说明\n\n[定位配置](../settings.py#L32) [返回项目说明](../README.zh-CN.md)\n\n<script>window.unexpected = true;</script>";
const sourceText = "# 配置\n" + "enabled = True\n".repeat(80);
const reply = [
  "# 文件引用",
  "打开 `README.zh-CN.md`、`gui/README.md`、[项目目录](examples/ai/) 或 `missing.txt`。",
  "`docs/" + "long-name-".repeat(35) + "readme.md`",
  ...Array.from({ length: 30 }, (_, index) => `第 ${index + 1} 段。This paragraph keeps the reading position away from the live draft.`),
].join("\n\n");

test("reads Workspace files on demand without moving the conversation or running preview HTML", async ({ page }, info) => {
  await page.setViewportSize({ width: 760, height: 760 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => Object.assign(window, { __LOUSHANG_MANAGED_TEST__: true }));
  const snapshot = liveSnapshot();
  snapshot.sessions[0].source.source.records[1].text = reply;
  snapshot.sessions[0].source.source.records.push({
    kind: "status", text: "Sending a message resumes the session runtime.",
  });
  const reads: { reference: string; base: string }[] = [];
  const entries = [{ name: "config.py", kind: "file" }, { name: "advanced", kind: "directory" }];
  const file = (path: string, text: string) => ({ kind: "file", path, text });
  const files = new Map<string, object>([
    ["|README.zh-CN.md", file("README.zh-CN.md", rootText)],
    ["|gui/README.md", file("gui/README.md", guiText)],
    ["gui|../settings.py", file("settings.py", sourceText)],
    ["gui|../README.zh-CN.md", file("README.zh-CN.md", rootText)],
    ["|examples/ai/", { kind: "directory", path: "examples/ai", entries, limited: false }],
    ["examples/ai|advanced", { kind: "directory", path: "examples/ai/advanced", entries: [], limited: false }],
    ["examples/ai|config.py", file("examples/ai/config.py", sourceText)],
  ]);
  await page.route("**/api/loushang", async (route) => {
    const request = route.request().postDataJSON();
    if (request.operation === "workspace" && request.action === "preview") {
      expect(request).toMatchObject({ path: "/workspace", fingerprint: "a".repeat(64), serviceInstanceId: "service-1" });
      const { reference, base } = request;
      reads.push({ reference, base });
      const result = files.get(base + "|" + reference);
      return route.fulfill({ json: result ? { result } : { error: "not_found" }, status: result ? 200 : 503 });
    }
    let result = {};
    if (request.operation === "environment") result = { supported: true, workspace: "/workspace" };
    else if (request.operation === "manage") result = { state: "running", serviceInstanceId: "service-1" };
    else if (request.action === "navigation") result = {
      projects: [{ path: "/workspace", sessions: [{ id: "session-1", title: "Live session", scope: "mux:mux-1", pinned: false }] }],
      temporarySessions: [],
    };
    else if (request.operation === "workspace" && request.action === "inspect") {
      expect(request.path).toBe("/workspace");
      result = { workspaces: [{
        scopeFingerprint: "a".repeat(64),
        inspection: { git: null, changes: [], toolchains: [{ name: "Node", declared: "24" }], limited: false },
      }] };
    }
    else if (request.action === "models") result = {
      currentId: "test",
      models: [{ id: "test", provider: "sample", endpointId: "local", modelId: "test", label: "Test", supportsThinking: false }],
    };
    else if (request.action === "snapshot") result = snapshot;
    return route.fulfill({ json: { result } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "Live session", exact: true }).click();
  const transcript = page.locator(".transcript");
  await expect(page.getByText("/workspace", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Node", exact: true })).toBeVisible();
  await expect(transcript.locator(".transcript-status")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Toggle environment" })).toHaveCount(0);
  await page.locator("#message-input").fill("Ready to continue");
  await expect(page.locator(".composer-submit")).toBeEnabled();
  await page.locator("#message-input").fill("");
  const trigger = transcript.getByRole("button", { name: "README.zh-CN.md", exact: true });
  await expect(trigger).toBeVisible();
  expect(reads).toEqual([]);
  expect(await transcript.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  await trigger.focus();
  const offset = await transcript.evaluate((node) => node.scrollTop);
  await trigger.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "当前工作区" })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "外部站点" })).toHaveAttribute("href", "https://example.com");
  await dialog.getByRole("button", { name: "Copy file path" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("README.zh-CN.md");
  await dialog.getByRole("button", { name: "Copy file contents" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(rootText);
  await dialog.getByRole("button", { name: "Source view" }).click();
  await expect(dialog.locator("pre")).toContainText("[GUI 说明](gui/README.md)");
  await dialog.getByRole("button", { name: "Source view" }).click();
  await dialog.getByRole("button", { name: "GUI 说明" }).click();
  await expect(dialog.getByRole("heading", { name: "GUI 说明" })).toBeVisible();
  expect(await page.evaluate(() => "unexpected" in window)).toBe(false);
  await dialog.getByRole("button", { name: "定位配置" }).click();
  await expect(dialog.getByText("Line 32")).toBeVisible();
  await expect(dialog.locator("pre .hljs-literal").first()).toBeVisible();
  expect(await dialog.locator("pre").evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("file-preview-dark.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await transcript.evaluate((node) => node.scrollTop)).toBe(offset);

  await transcript.getByRole("button", { name: "gui/README.md" }).click();
  await dialog.getByRole("button", { name: "返回项目说明" }).click();
  await expect(dialog.getByRole("heading", { name: "当前工作区" })).toBeVisible();
  await page.keyboard.press("Escape");

  await transcript.getByRole("button", { name: "项目目录" }).click();
  await dialog.getByRole("button", { name: "advanced/" }).click();
  await expect(dialog.getByText("No previewable entries in this folder.")).toBeVisible();
  await dialog.getByRole("button", { name: "Back", exact: true }).click();
  await dialog.getByRole("button", { name: "config.py" }).click();
  await expect(dialog.locator("pre")).toContainText("enabled = True");
  await dialog.getByRole("button", { name: "Close file preview" }).click();
  await transcript.getByRole("button", { name: "missing.txt" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("The Host could not find this path in the current Workspace.");
  await page.keyboard.press("Escape");

  await transcript.evaluate((node) => { node.scrollTop = 170; });
  await expect.poll(() => transcript.evaluate((node) => node.scrollTop)).toBe(170);
  snapshot.sessions[0].source.observation = { executionId: "draft-execution", status: "running", finalCursor: null };
  snapshot.sessions[0].source.draft = "Streaming draft";
  await expect(transcript.getByText("Streaming draft")).toBeAttached();
  expect(await transcript.evaluate((node) => node.scrollTop)).toBe(170);
  expect(reads).toContainEqual({ base: "gui", reference: "../README.zh-CN.md" });
});

test("shows a temporary Workspace path, previews a bare artifact and copies the full turn", async ({ page }) => {
  const path = "/host/workspaces/temporary/weather";
  const externalUrl = "https://example.com/search?q=weather#today";
  const progress = "正在生成天气页面。";
  const final = `已完成：index.html。打开[参考资料](${externalUrl})。`;
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => Object.assign(window, { __LOUSHANG_MANAGED_TEST__: true }));
  const snapshot = liveSnapshot();
  snapshot.sessions[0].source.source.records = [
    { kind: "user", text: "生成天气页面" },
    { kind: "assistant", text: progress },
    { kind: "assistant", text: final },
  ];
  await page.route("**/api/loushang", async (route) => {
    const request = route.request().postDataJSON();
    let result = {};
    if (request.operation === "environment") result = { supported: true, workspace: "@temporary" };
    else if (request.operation === "manage") result = { state: "running", serviceInstanceId: "service-1" };
    else if (request.action === "navigation") result = {
      projects: [],
      temporarySessions: [{ id: "session-1", title: "Live session", scope: "mux:mux-1", pinned: false }],
    };
    else if (request.action === "snapshot") result = snapshot;
    else if (request.action === "locate") result = { path };
    else if (request.action === "preview") {
      expect(request).toMatchObject({ path: "@temporary", reference: "index.html", fingerprint: "a".repeat(64) });
      result = { kind: "file", path: "index.html", text: "<h1>Weather</h1>" };
    }
    return route.fulfill({ json: { result } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "Live session", exact: true }).click();
  await expect(page.locator(".workspace-location-path code")).toHaveText(path);
  const transcript = page.locator(".transcript");
  await expect(transcript.locator(".reply-actions")).toHaveCount(1);
  const copy = transcript.getByRole("button", { name: "Copy reply" });
  await copy.focus();
  await copy.press("Enter");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(progress + "\n\n" + final);
  const link = transcript.getByRole("link", { name: "参考资料" });
  await expect(link).toHaveAttribute("href", externalUrl);
  await expect(link).toHaveAttribute("target", "_blank");
  await transcript.getByRole("button", { name: "index.html" }).click();
  await expect(page.getByRole("dialog").locator("pre")).toHaveText("<h1>Weather</h1>");
});
