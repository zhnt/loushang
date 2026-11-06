import { describe, expect, it } from "vitest";
import { resolveLanguage, parsePreference } from "../../src/i18n/language";

describe("language preference", () => {
  it.each([
    ["en-US", ["zh-CN"], "en-US"],
    ["zh-CN", ["en-US"], "zh-CN"],
    ["system", ["de-DE", "zh-SG"], "zh-CN"],
    ["system", ["zh-Hans", "en-US"], "zh-CN"],
    ["system", ["zh-Hant-CN", "en-GB"], "en-US"],
    ["system", ["zh-TW", "zh-HK"], "en-US"],
    ["system", ["en-GB", "zh-CN"], "en-US"],
    ["system", ["zh"], "zh-CN"],
    ["system", ["bad_locale", "zh-CN"], "zh-CN"],
    ["system", [], "en-US"],
  ] as const)("resolves %s with %j", (preference, languages, expected) => {
    expect(resolveLanguage(preference, languages)).toBe(expected);
  });
  it.each([null, "", "fr", "__proto__"])("recovers unknown preference %s", (value) => {
    expect(parsePreference(value)).toBe("system");
  });
  it.each(["system", "en-US", "zh-CN"])("retains preference %s", (value) => {
    expect(parsePreference(value)).toBe(value);
  });
});
