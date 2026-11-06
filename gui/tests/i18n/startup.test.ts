import { expect, it, vi } from "vitest";
import { i18n, initializeI18n, systemLanguages } from "../../src/i18n";
import { readPreference, languageStorageKey } from "../../src/i18n/language";
const platform = vi.hoisted(() => { vi.resetModules(); return ({ native: false, locale: vi.fn(async (): Promise<string | null> => "zh-CN") }); });
vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => platform.native }));
vi.mock("@tauri-apps/plugin-os", () => ({ locale: platform.locale }));

it("restores the saved language on startup and preserves unrelated settings", async () => {
  localStorage.setItem(languageStorageKey, "zh-CN");
  localStorage.setItem("existing-setting", "preserve");
  await initializeI18n(["en-US"]);
  expect(i18n.language).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");
  expect(localStorage.getItem("existing-setting")).toBe("preserve");
});
it("reads the native locale rather than assuming the WebView locale", async () => {
  platform.native = true;
  try { expect(await systemLanguages()).toEqual(["zh-CN"]); }
  finally { platform.native = false; }
});
it("keeps follow-system as a preference and resolves it anew at startup", async () => {
  localStorage.setItem(languageStorageKey, "system");
  await initializeI18n(["zh-CN"]);
  expect(i18n.language).toBe("zh-CN");
  await initializeI18n(["en-US"]);
  expect(i18n.language).toBe("en-US");
  expect(readPreference()).toBe("system");
});
it("starts even if the preference storage cannot be read", async () => {
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
  try {
    await initializeI18n(["zh-CN"]);
    expect(i18n.language).toBe("zh-CN");
  } finally { read.mockRestore(); }
});
it("falls back to English when native locale detection fails", async () => {
  platform.native = true;
  platform.locale.mockRejectedValueOnce(new Error("unavailable"));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  try {
    await initializeI18n();
    expect(i18n.language).toBe("en-US");
    expect(warn).toHaveBeenCalledOnce();
  } finally { platform.native = false; warn.mockRestore(); }
});

it("starts in English when the native platform returns no locale", async () => {
  platform.native = true;
  platform.locale.mockResolvedValueOnce(null);
  try {
    await initializeI18n();
    expect(i18n.language).toBe("en-US");
    expect(document.documentElement.lang).toBe("en-US");
  } finally { platform.native = false; }
});
