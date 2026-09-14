import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const userRoot = process.env.USERPROFILE ?? process.env.HOME;
const localCargo = userRoot ? path.join(userRoot, ".cargo/bin", process.platform === "win32" ? "cargo.exe" : "cargo") : "cargo";
const cargo = existsSync(localCargo) ? localCargo : "cargo";
function invoke(command, args, input) {
  const result = spawnSync(command, args, { cwd: root, input, encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error || result.status !== 0) throw new Error(`${command} failed: ${result.error?.message ?? result.status}`);
  return result.stdout;
}
try {
  const vectors = invoke("uv", ["run", "python", "scripts/gui/contract_vectors.py"]);
  const bridge = invoke(cargo, ["+1.98.1", "run", "--locked", "--offline", "--quiet", "--manifest-path", "gui/contracts/rust/Cargo.toml"], vectors);
  process.stdout.write(invoke(process.execPath, ["gui/contracts/verify.ts"], bridge));
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
