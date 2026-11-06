import { createInstance } from "i18next";
import { expect, it } from "vitest";
import { resources } from "../../src/i18n/resources";

it("falls back to readable English for empty and missing translations", async () => {
  const data = structuredClone(resources);
  data["zh-CN"].session.composer.send = "";
  Reflect.deleteProperty(data["zh-CN"].session.composer, "interrupt");
  const instance = createInstance();
  await instance.init({ resources: data, lng: "zh-CN", fallbackLng: "en-US", returnEmptyString: false });
  expect(instance.t("session:composer.send")).toBe("Send");
  expect(instance.t("session:composer.interrupt")).toBe("Interrupt");
});
it("selects language-specific plural forms and formats counts", async () => {
  const instance = createInstance();
  await instance.init({ resources, lng: "en-US" });
  expect(instance.t("session:fixture.queued", { count: 1 })).toBe("1 queued event");
  expect(instance.t("session:fixture.queued", { count: 2000 })).toBe("2,000 queued events");
  await instance.changeLanguage("zh-CN");
  expect(instance.t("session:fixture.queued", { count: 1 })).toBe("待回放 1 个事件");
  expect(instance.t("session:fixture.queued", { count: 2000 })).toBe("待回放 2,000 个事件");
});
