import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { hostBridge } from "./hostBridge.ts";
import { readFileSync } from "node:fs";
import process from "node:process";
const host = process.env.TAURI_DEV_HOST;
const config = JSON.parse(readFileSync(new URL("./src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const htmlTitle = config.productName.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    { name: "gui-title", transformIndexHtml: (html) => html.replace("__GUI_PRODUCT_NAME__", () => htmlTitle) },
    ...(mode === "desktop" ? [] : [hostBridge()]),
  ],

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
