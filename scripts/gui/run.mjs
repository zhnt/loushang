import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const guiDir = path.resolve(scriptDir, "..", "..", "gui");
const manifest = path.join(guiDir, "src-tauri", "Cargo.toml");
const cargo = rustTool("cargo");
const rustc = rustTool("rustc");
const pnpmEntry = process.env.npm_execpath;
const childEnv = path.isAbsolute(cargo)
  ? {
      ...process.env,
      PATH: `${path.dirname(cargo)}${path.delimiter}${process.env.PATH ?? ""}`,
    }
  : process.env;

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

if (!pnpmEntry) {
  process.stderr.write("Run this script through a pnpm package command.\n");
  process.exit(1);
}

function runPnpm(args) {
  run(process.execPath, [pnpmEntry, ...args]);
}

function capturePnpm(args) {
  return capture(process.execPath, [pnpmEntry, ...args]);
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
  expectPrefix("node", process.version, "v24.19.0");
  expectPrefix("pnpm", capturePnpm(["--version"]), "11.19.0");
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
  runPnpm(["exec", "tsc", "--noEmit"]);
  runPnpm(["exec", "vite", "build"]);
}

function runNative(command, fixtureBridge = false) {
  const args = ["exec", "tauri", command];
  if (command === "build") args.push("--no-bundle");
  if (fixtureBridge) args.push("--features", "fixture-bridge");
  runPnpm(args);
}

function check() {
  runPnpm(["exec", "tsc", "--noEmit"]);
  runPnpm(["exec", "vitest", "run"]);
}

function checkFull() {
  doctor();
  buildWeb();
  runPnpm(["exec", "vitest", "run"]);
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
  } else if (mode === "dev-fixture-native") {
    runNative("dev", true);
  } else if (mode === "build-native") {
    runNative("build");
  } else if (mode === "build-fixture-native") {
    runNative("build", true);
  } else {
    throw new Error(`unknown GUI command mode: ${mode ?? "<missing>"}`);
  }
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}
