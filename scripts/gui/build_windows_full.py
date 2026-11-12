"""Build a Windows x64 NSIS installer with GUI, TUI, Web, and AppHost."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "gui"
TAURI = GUI / "src-tauri"


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def stage_runtime(work: Path) -> None:
    python = subprocess.check_output(
        ["uv", "python", "find", "--managed-python", "3.11"], text=True, cwd=ROOT,
    ).strip()
    prefix = subprocess.check_output(
        [python, "-I", "-c", "import sys; print(sys.base_prefix)"], text=True,
    ).strip()
    runtime = work / "runtime"
    shutil.copytree(prefix, runtime, ignore=shutil.ignore_patterns("__pycache__"))
    sites = runtime / "Lib/site-packages"
    if sites.exists():
        shutil.rmtree(sites)
    requirements = work / "requirements.txt"
    run("uv", "export", "--locked", "--no-dev", "--no-emit-project", "--output-file",
        str(requirements))
    bundled = str(runtime / "python.exe")
    install = ("uv", "pip", "install", "--python", bundled, "--target", str(sites))
    run(*install, "--require-hashes", "--no-deps", "-r", str(requirements))
    run("uv", "build", "--wheel", "--out-dir", str(work))
    run(*install, "--no-deps", str(next(work.glob("loushang-*.whl"))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/windows-full")
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().upper() != "AMD64":
        parser.error("this recipe targets Windows x64")
    output = args.output.resolve()
    version = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    name = f"loushang-gui_{version}_x64-setup.exe"
    if (output / name).exists():
        parser.error(f"refusing to overwrite {output / name}")

    env = {**os.environ, "RUSTUP_TOOLCHAIN": "1.98.1-x86_64-pc-windows-msvc"}
    with tempfile.TemporaryDirectory(prefix="windows-full-", dir=TAURI) as directory:
        work = Path(directory)
        stage_runtime(work)
        run(sys.executable, str(Path(__file__).with_name("build_windows_tui.py")),
            "--output", str(work))
        run("rustc", "--edition=2021", "-O", "-C", "target-feature=+crt-static",
            str(Path(__file__).with_name("windows_mux_entry.rs")),
            "-o", str(work / "loushang-mux.exe"), env=env)
        run("cargo", "build", "--locked", "--release", "--manifest-path",
            str(GUI / "web/Cargo.toml"), env=env)
        shutil.copy2(GUI / "web/target/release/loushang-web.exe", work)
        run("npm.cmd", "ci", cwd=GUI)
        config = {
            "bundle": {
                "windows": {
                    "bundleVCRuntime": True,
                    "webviewInstallMode": {"type": "offlineInstaller", "silent": True},
                },
                "resources": {
                    f"{work.name}/runtime/": "runtime/",
                    f"{work.name}/loushang.exe": "loushang.exe",
                    f"{work.name}/loushang-mux.exe": "loushang-mux.exe",
                    f"{work.name}/loushang-web.exe": "loushang-web.exe",
                    "../dist/": "web/",
                },
            },
        }
        config_path = work / "bundle.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        run(str(GUI / "node_modules/.bin/tauri.cmd"), "build", "--bundles", "nsis",
            "--config", str(config_path), cwd=GUI, env=env)
        output.mkdir(parents=True, exist_ok=True)
        source = TAURI / "target/release/bundle/nsis" / name
        with source.open("rb") as installer, (output / name).open("xb") as destination:
            shutil.copyfileobj(installer, destination)
    print(output / name)


if __name__ == "__main__":
    main()
