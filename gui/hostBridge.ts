import type { Plugin } from "vite";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
const execute = promisify(execFile);

/** Vite only proxies HTTP; the GUI Rust binary owns the shared listener. */
export function hostBridge(): Plugin {
  return {
    name: "loushang-host-bridge",
    async configureServer(server) {
      const root = path.resolve(import.meta.dirname, "..");
      const manifest = path.join(root, "gui/web/Cargo.toml");
      let binary = process.env.LOUSHANG_GUI_WEB;
      if (!binary) {
        await execute("cargo", ["build", "--locked", "--manifest-path", manifest], { cwd: path.join(root, "gui") });
        binary = path.join(root, "gui/web/target/debug", process.platform === "win32" ? "loushang-web.exe" : "loushang-web");
      }
      const manager = path.join(root, ".venv", "Scripts", "loushang-mux.exe");
      const env = process.platform === "win32" && !process.env.LOUSHANG_MUX
        ? { ...process.env, LOUSHANG_MUX: manager }
        : process.env;
      const { stdout } = await execute(binary, ["--ensure"], { cwd: root, env });
      const endpoint = new URL(stdout.trim());
      server.middlewares.use("/api/loushang", async (request, response) => {
        response.setHeader("Content-Type", "application/json");
        response.setHeader("Cache-Control", "no-store");
        const host = request.headers.host;
        const origin = request.headers.origin;
        if (request.method !== "POST" || !host || !/^(localhost|127\.0\.0\.1|\[::1\]):\d+$/.test(host)
          || (origin && origin !== `http://${host}`) || request.headers["x-loushang-client"] !== "1") {
          response.statusCode = 403;
          response.end('{"error":"forbidden"}');
          return;
        }
        try {
          let body = "";
          for await (const chunk of request) {
            body += chunk;
            if (Buffer.byteLength(body) > 1_000_000) throw new Error("request_too_large");
          }
          const result = await fetch(new URL("/api/loushang", endpoint), {
            method: "POST", body, headers: { "Content-Type": "application/json", "X-Loushang-Client": "1" },
            signal: AbortSignal.timeout(110_000), redirect: "error",
          });
          response.statusCode = result.status;
          response.end(await result.text());
        } catch {
          response.statusCode = 503;
          response.end('{"error":"host_request_failed"}');
        }
      });
    },
  };
}
