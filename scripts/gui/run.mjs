import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "..", "..");
const guiDir = path.join(projectDir, "gui");
const manifest = path.join(guiDir, "src-tauri", "Cargo.toml");
const cargo = rustTool("cargo");
const rustc = rustTool("rustc");
const npmEntry = process.env.npm_execpath;
const childEnv = {
  ...process.env,
  ...(path.isAbsolute(cargo) ? { PATH: `${path.dirname(cargo)}${path.delimiter}${process.env.PATH ?? ""}` } : {}),
};

function rustTool(name) {
  const executable = process.platform === "win32" ? `${name}.exe` : name;
  const userRoot = process.platform === "win32"
    ? process.env.USERPROFILE
    : process.env.HOME;
  if (userRoot) {
    const userInstall = path.join(userRoot, ".cargo", "bin", executable);
    if (existsSync(userInstall)) return userInstall;
  }
  return executable;
}

if (!npmEntry) {
  process.stderr.write("Run this script through an npm package command.\n");
  process.exit(1);
}

function runNpm(args) {
  run(process.execPath, [npmEntry, ...args]);
}

function captureNpm(args) {
  return capture(process.execPath, [npmEntry, ...args]);
}

function run(command, args) {
  const rendered = [command, ...args].join(" ");
  process.stdout.write(`> ${rendered}\n`);
  const result = spawnSync(command, args, {
    cwd: guiDir,
    env: childEnv,
    stdio: "inherit",
  });
  if (result.error) {
    process.stderr.write(`${rendered}: ${result.error.message}\n`);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function capture(command, args) {
  const result = spawnSync(command, args, {
    cwd: guiDir,
    env: childEnv,
    encoding: "utf8",
  });
  if (result.error || result.status !== 0) {
    const detail = result.error?.message ?? result.stderr?.trim() ?? "unknown error";
    throw new Error(`${command} ${args.join(" ")} failed: ${detail}`);
  }
  return result.stdout.trim();
}

function expectPrefix(label, actual, expected) {
  if (!actual.startsWith(expected)) {
    throw new Error(`${label}: expected ${expected}, found ${actual}`);
  }
  process.stdout.write(`${label}: ${actual}\n`);
}

function doctor() {
  const { engines } = JSON.parse(readFileSync(path.join(guiDir, "package.json"), "utf8"));
  expectPrefix("node", process.version, `v${engines.node.split(".")[0]}.`);
  expectPrefix("npm", captureNpm(["--version"]), `${engines.npm.split(".")[0]}.`);
  expectPrefix("rustc", capture(rustc, ["--version"]), "rustc 1.98.1 ");
  expectPrefix("cargo", capture(cargo, ["--version"]), "cargo 1.98.1 ");
  const verboseRustc = capture(rustc, ["--version", "--verbose"]);
  const hostLine = verboseRustc.split(/\r?\n/).find((line) => line.startsWith("host: "));
  if (!hostLine) {
    throw new Error("rustc did not report a host target");
  }
  if (process.platform === "win32" && hostLine !== "host: x86_64-pc-windows-msvc") {
    throw new Error(`Windows requires the MSVC Rust host; found ${hostLine}`);
  }
  process.stdout.write(`${hostLine}\n`);
}

function buildWeb() {
  runNpm(["exec", "--", "tsc", "--noEmit"]);
  runNpm(["exec", "--", "vite", "build"]);
}

function prepareDevMux() {
  const windows = process.platform === "win32";
  if ((!windows && process.platform !== "linux") || childEnv.LOUSHANG_MUX || childEnv.LOUSHANG_APP_RECORD_ROOT) return;

  const environment = path.resolve(projectDir, childEnv.UV_PROJECT_ENVIRONMENT || ".venv");
  const mux = windows
    ? path.join(environment, "Scripts", "loushang-mux.exe")
    : path.join(environment, "bin", "loushang-mux");
  let installed = statSync(mux, { throwIfNoEntry: false })?.isFile();
  if (windows && !installed) {
    process.stdout.write("Preparing the local AppHost with uv sync --locked.\n");
    const sync = spawnSync("uv", ["sync", "--locked"], {
      cwd: projectDir,
      env: childEnv,
      stdio: "inherit",
    });
    if (sync.error || sync.status !== 0) {
      const reason = sync.error?.message ?? `uv exited with status ${sync.status}`;
      process.stderr.write(`Could not prepare the local AppHost (${reason}).\n`);
    }
    installed = sync.status === 0 && statSync(mux, { throwIfNoEntry: false })?.isFile();
  }
  if (installed) {
    childEnv.LOUSHANG_MUX = mux;
    if (!windows) childEnv.LOUSHANG_MUX_BACKEND ??= "managed";
  } else {
    process.stderr.write(`Local AppHost command not found at ${mux}.\n`);
    process.stderr.write("Run uv sync --locked in this checkout or set LOUSHANG_MUX to the absolute path of the installed command.\n");
  }
}

function runNative(command, fixtureBridge = false) {
  if (command === "dev") prepareDevMux();
  const webManifest = path.join(guiDir, "web", "Cargo.toml");
  if (command === "build") run(cargo, ["build", "--locked", "--manifest-path", webManifest, "--release"]);
  const args = ["exec", "--", "tauri", command];
  if (command === "build") args.push("--no-bundle");
  if (fixtureBridge) args.push("--features", "fixture-bridge");
  runNpm(args);
  if (command === "build") {
    const name = process.platform === "win32" ? "loushang-web.exe" : "loushang-web";
    const destination = path.join(guiDir, "src-tauri", "target", "release");
    mkdirSync(destination, { recursive: true });
    copyFileSync(path.join(guiDir, "web", "target", "release", name), path.join(destination, name));
  }
}

function check() {
  runNpm(["exec", "--", "tsc", "--noEmit"]);
  runNpm(["exec", "--", "vitest", "run"]);
}

function checkFull() {
  doctor();
  buildWeb();
  runNpm(["exec", "--", "vitest", "run"]);
  run(cargo, ["fmt", "--manifest-path", manifest, "--", "--check"]);
  run(cargo, ["clippy", "--locked", "--manifest-path", manifest, "--all-targets", "--", "-D", "warnings"]);
  run(cargo, ["clippy", "--locked", "--manifest-path", manifest, "--all-targets", "--features", "fixture-bridge", "--", "-D", "warnings"]);
  run(cargo, ["check", "--locked", "--manifest-path", manifest]);
  run(cargo, ["check", "--locked", "--manifest-path", manifest, "--features", "fixture-bridge"]);
}

const mode = process.argv[2];
try {
  if (mode === "doctor") {
    doctor();
  } else if (mode === "build-web") {
    buildWeb();
  } else if (mode === "check") {
    check();
  } else if (mode === "check-full") {
    checkFull();
  } else if (mode === "dev-native") {
    runNative("dev");
  } else if (mode === "build-native") {
    runNative("build");
  } else {
    throw new Error(`unknown GUI command mode: ${mode ?? "<missing>"}`);
  }
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}
