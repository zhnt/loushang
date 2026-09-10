import { describe, expect, it } from "vitest";
import manifest from "./playback/cases.json";

describe("GUI playback case manifest", () => {
  it("has stable unique IDs and no empty required platform set", () => {
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.cases.length).toBeGreaterThan(0);
    expect(new Set(manifest.cases.map((item) => item.id)).size).toBe(
      manifest.cases.length,
    );
    for (const item of manifest.cases) {
      expect(item.id).toMatch(/^GUI-B1-L[0-2]-/);
      expect(item.requiredOn.length).toBeGreaterThan(0);
      expect(item.command).toMatch(/^pnpm run /);
      expect(item.intent.trim()).not.toBe("");
    }
  });
});
