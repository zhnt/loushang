import { defineConfig } from "i18next-cli";
export default defineConfig({
  locales: ["en-US", "zh-CN"],
  extract: {
    input: ["src/**/*.{ts,tsx}"],
    ignore: ["src/i18n/generated/**", "src/client/**"],
    output: "src/i18n/locales/{{language}}/{{namespace}}.json",
    defaultNS: "shell",
    removeUnusedKeys: false,
  },
  lint: {
    checkInterpolationParams: true,
    checkTranslationPlaceholders: "error",
  },
  types: {
    input: ["src/i18n/locales/en-US/*.json"],
    output: "src/i18n/generated/i18next.d.ts",
    resourcesFile: "src/i18n/generated/resources.d.ts",
    enableSelector: false,
  },
});
