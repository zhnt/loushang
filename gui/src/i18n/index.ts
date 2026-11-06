import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import { isTauri } from "@tauri-apps/api/core";
import { locale } from "@tauri-apps/plugin-os";
import { resources } from "./resources";
import { readPreference, resolveLanguage } from "./language";

export const i18n = i18next.createInstance();

export async function systemLanguages(): Promise<readonly string[]> {
  if (!isTauri()) return navigator.languages;
  try {
    const language = await locale();
    return language ? [language] : [];
  } catch (error) {
    console.warn("Could not read the system locale", error);
    return [];
  }
}

export async function initializeI18n(languages?: readonly string[]): Promise<void> {
  const lng = resolveLanguage(readPreference(), languages ?? await systemLanguages());
  await i18n.use(initReactI18next).init({
    resources,
    lng,
    supportedLngs: ["en-US", "zh-CN"],
    fallbackLng: "en-US",
    defaultNS: "shell",
    returnEmptyString: false,
    interpolation: { escapeValue: false },
  });
  document.documentElement.lang = lng;
}
