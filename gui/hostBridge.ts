import type { Plugin } from "vite";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { existsSync } from "node:fs";

/** Private stdio adapter: no Host secrets or local record paths enter the browser. */
export function hostBridge(): Plugin {
  return {
    name: "loushang-host-bridge",
    configureServer(server) {
      const root = path.resolve(import.meta.dirname, "..");
      const localPython = path.join(root, ".venv", "bin", "python");
      const python = process.env.LOUSHANG_GUI_PYTHON ?? (existsSync(localPython) ? localPython : "python3");
      const child = spawn(python, ["-m", "loushang.coding.web_gateway"], {
        cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "src") }, stdio: ["pipe", "pipe", "inherit"],
      });
      let sequence = 0;
      const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
      const lines = createInterface({ input: child.stdout });
      lines.on("line", (line) => {
        try {
          const reply = JSON.parse(line);
          const request = pending.get(reply.id);
          pending.delete(reply.id);
          if (reply.error) request?.reject(new Error(reply.error));
          else request?.resolve(reply.result);
        } catch { fail(); }
      });
      let stopped = false;
      function fail() {
        stopped = true;
        for (const request of pending.values()) request.reject(new Error("host_unavailable"));
        pending.clear();
      }
      child.on("error", fail);
      child.on("exit", fail);
      server.httpServer?.once("close", () => { fail(); child.stdin.end(); });
      server.middlewares.use("/api/loushang", async (request, response) => {
        response.setHeader("Content-Type", "application/json");
        response.setHeader("Cache-Control", "no-store");
        // Vite is a local development surface, not an unauthenticated remote gateway.
        const host = request.headers.host;
        const origin = request.headers.origin;
        if (request.method !== "POST" || !host || !/^(localhost|127\.0\.0\.1|\[::1\]):\d+$/.test(host)
          || (origin && origin !== `http://${host}`) || request.headers["x-loushang-client"] !== "1") {
          response.statusCode = 403;
          response.end(JSON.stringify({ error: "forbidden" }));
          return;
        }
        try {
          if (stopped || pending.size >= 64) throw new Error("host_unavailable");
          let body = "";
          for await (const chunk of request) {
            body += chunk;
            if (Buffer.byteLength(body) > 1_000_000) throw new Error("request_too_large");
          }
          const input = JSON.parse(body);
          const id = ++sequence;
          let timer: ReturnType<typeof setTimeout>;
          const result = await new Promise((resolve, reject) => {
            timer = setTimeout(() => { pending.delete(id); reject(new Error("host_timeout")); }, 80_000);
            pending.set(id, { resolve, reject });
            child.stdin.write(`${JSON.stringify({ id, request: input })}\n`, (error) => {
              if (error) { pending.delete(id); reject(new Error("host_unavailable")); }
            });
          }).finally(() => clearTimeout(timer));
          response.end(JSON.stringify({ result }));
        } catch (error) {
          response.statusCode = 503;
          response.end(JSON.stringify({ error: error instanceof Error && /^[a-z_]+$/.test(error.message) ? error.message : "host_request_failed" }));
        }
      });
    },
  };
}
