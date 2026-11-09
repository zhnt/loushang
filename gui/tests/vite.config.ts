import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Deterministic browser playback is a test entrypoint, never a product mode.
export default defineConfig({
  plugins: [react(), {
    name: "test-only-entry",
    transformIndexHtml(html) { return html.replace('/src/main.tsx', '/tests/browser/main.tsx'); },
  }],
});
