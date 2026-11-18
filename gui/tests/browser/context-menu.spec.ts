import { expect, test } from "@playwright/test";

test("right click opens the app's session and text actions", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await page.locator(".collapsed-rail .frame-icon").click();

  const session = page.getByRole("button", { name: "Operational ontology · Idle" });
  await session.click({ button: "right" });
  const menu = page.getByRole("menu", { name: "Context menu" });
  await menu.getByRole("menuitem", { name: "Pin" }).click();
  const pinned = page.getByRole("region", { name: "Pinned" });
  const pinnedSession = pinned.getByRole("button", { name: "Operational ontology · Idle" });
  await pinnedSession.click();
  await pinnedSession.click({ button: "right" });
  await expect(menu.getByRole("menuitem", { name: "Unpin" })).toBeVisible();
  await page.keyboard.press("Escape");

  const editor = page.getByRole("textbox");
  await editor.fill("first line");
  await editor.selectText();
  await editor.click({ button: "right", position: { x: 10, y: 10 } });
  await menu.getByRole("menuitem", { name: "Copy" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("first line");

  await page.evaluate(() => navigator.clipboard.writeText("第二行"));
  await editor.selectText();
  await editor.click({ button: "right", position: { x: 10, y: 10 } });
  await menu.getByRole("menuitem", { name: "Paste" }).click();
  await expect(editor).toHaveValue("第二行");
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();

  await editor.click({ button: "right", position: { x: 10, y: 10 } });
  await menu.getByRole("menuitem", { name: "Select all" }).click();
  await editor.click({ button: "right", position: { x: 10, y: 10 } });
  await menu.getByRole("menuitem", { name: "Cut" }).click();
  await expect(editor).toHaveValue("");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("第二行");

  const suppressed = await page.locator(".desktop-shell").evaluate((shell) =>
    !shell.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true })));
  expect(suppressed).toBe(true);
  await expect(menu).toHaveCount(0);
});
