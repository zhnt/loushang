"""Build a Full Windows installer from the current checkout."""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from internal.common import (
    GUI,
    PYTHON,
    ROOT,
    arguments,
    digest,
    prepare_npm,
    provenance,
    publish,
    require_tools,
    wheel,
)
from internal.windows_tui import build_tui

TAURI = GUI / "src-tauri"
INSTALLER_CHECKS = Path(__file__).parent / "internal/windows"
# Preserve Tauri's historical UpgradeCode for this product name.
MSI_UPGRADE_CODE = "e70965de-1a4b-568b-b7f9-92f454bd1b4b"


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def stage_runtime(work: Path, product_wheel: Path, requirements: Path) -> None:
    python = subprocess.check_output(
        ["uv", "python", "find", "--system", "--managed-python", PYTHON], text=True, cwd=ROOT,
    ).strip()
    prefix = subprocess.check_output(
        [python, "-I", "-c", "import sys; print(sys.base_prefix)"], text=True,
    ).strip()
    runtime = work / "runtime"
    shutil.copytree(prefix, runtime, ignore=shutil.ignore_patterns("__pycache__"))
    sites = runtime / "Lib/site-packages"
    if sites.exists():
        shutil.rmtree(sites)
    run("uv", "--quiet", "export", "--locked", "--no-dev", "--no-emit-project", "--output-file",
        str(requirements))
    bundled = str(runtime / "python.exe")
    install = ("uv", "pip", "install", "--python", bundled, "--target", str(sites))
    run(*install, "--require-hashes", "--only-binary", ":all:", "--no-deps", "-r", str(requirements))
    run(*install, "--no-deps", str(product_wheel))


def require_machine(path: Path, expected: int) -> None:
    with path.open("rb") as binary:
        if binary.read(2) != b"MZ":
            raise ValueError(f"Expected a PE executable: {path}")
        binary.seek(0x3C)
        offset, = struct.unpack("<I", binary.read(4))
        binary.seek(offset)
        if binary.read(6) != b"PE\0\0" + struct.pack("<H", expected):
            raise ValueError(f"Unexpected PE architecture: {path}")


def bundle_installer(
    tauri: str, work: Path, release: Path, env: dict[str, str], output: Path,
    package_format: str, facts: dict, product_wheel: Path,
) -> None:
    version = facts["version"]
    (work / "manifest.json").write_text(json.dumps({
        **facts, "format": f"loushang-windows-{package_format}/v1", "architecture": "x86_64",
        "wheelSha256": digest(product_wheel), "lockSha256": digest(ROOT / "uv.lock"),
    }, indent=2) + "\n", encoding="utf-8")
    config = {
        "version": version,
        "bundle": {
            "windows": {
                "bundleVCRuntime": True,
                "webviewInstallMode": {"type": "downloadBootstrapper", "silent": True},
                "nsis": {
                    "installMode": "currentUser",
                    "installerHooks": str(INSTALLER_CHECKS / "nsis-checks.nsh"),
                },
            },
            "resources": {
                f"{work.name}/runtime/": "runtime/",
                f"{work.name}/loushang.exe": "loushang.exe",
                f"{work.name}/loushang-mux.exe": "loushang-mux.exe",
                f"{work.name}/loushang-web.exe": "loushang-web.exe",
                "../dist/": "web/",
                **{f"{work.name}/{name}": name for name in (
                    "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "manifest.json",
                )},
            },
        },
    }
    if package_format == "msi":
        config["bundle"]["windows"].update(
            allowDowngrades=False,
            wix={
                "upgradeCode": MSI_UPGRADE_CODE,
                "fragmentPaths": [str(INSTALLER_CHECKS / "msi-checks.wxs")],
                "componentGroupRefs": ["LoushangInstallChecks"],
            },
        )
    config_path = work / "bundle.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    bundle = release / "bundle" / package_format
    extension = ".exe" if package_format == "nsis" else ".msi"
    pattern = f"loushang-gui_{version}_x64*{extension}"
    for previous in bundle.glob(pattern):
        previous.unlink()
    run(tauri, "bundle", "--bundles", package_format, "--config", str(config_path),
        cwd=GUI, env=env)
    (source,) = bundle.glob(pattern)
    magic = b"MZ" if package_format == "nsis" else bytes.fromhex("D0CF11E0A1B11AE1")
    with source.open("rb") as installer:
        if installer.read(len(magic)) != magic:
            raise RuntimeError(f"Unexpected {package_format} installer signature")

    suffix = "-setup.exe" if package_format == "nsis" else ".msi"
    with tempfile.TemporaryDirectory(prefix=".loushang-windows-", dir=output) as staging:
        package = Path(staging) / f"loushang-{version}-x64{suffix}"
        shutil.copy2(source, package)
        publish(package, output)


def main() -> None:
    args = arguments(__doc__, "Windows", ("nsis", "msi", "all"))
    if args.arch == "aarch64":
        raise SystemExit("Windows ARM64 requires a native wheel for locked cryptography==48.0.1")
    formats = ("nsis", "msi") if args.format == "all" else (args.format,)
    machine = 0x8664
    target = "x86_64-pc-windows-msvc"
    require_tools("git", "uv", "node", "npm.cmd", "rustc", "cargo")
    facts = provenance()
    version = facts["version"]
    if "msi" in formats and any(
        value > limit for value, limit in zip(map(int, version.split(".")), (255, 255, 65535))
    ):
        raise SystemExit("MSI version limits are 255.255.65535")
    env = {**os.environ, "RUSTUP_TOOLCHAIN": f"1.98.1-{target}"}
    env.pop("CARGO_BUILD_TARGET", None)
    env.pop("CARGO_TARGET_DIR", None)
    os.environ["RUSTUP_TOOLCHAIN"] = env["RUSTUP_TOOLCHAIN"]
    args.output.mkdir(parents=True, exist_ok=True)
    run("uv", "python", "install", PYTHON)
    prepare_npm()
    with tempfile.TemporaryDirectory(prefix="windows-full-", dir=TAURI) as directory:
        work = Path(directory)
        product_wheel = wheel(work)
        requirements = work / "requirements.txt"
        stage_runtime(work, product_wheel, requirements)
        require_machine(work / "runtime/python.exe", machine)
        build_tui(work / "loushang.exe", product_wheel, requirements)
        run("rustc", "--edition=2021", "-O", "-C", "target-feature=+crt-static",
            str(ROOT / "scripts/gui/windows_mux_entry.rs"),
            "-o", str(work / "loushang-mux.exe"), env=env)
        run("cargo", "build", "--locked", "--release", "--manifest-path",
            str(GUI / "web/Cargo.toml"), env=env)
        shutil.copy2(GUI / "web/target/release/loushang-web.exe", work)
        for name in ("loushang.exe", "loushang-mux.exe", "loushang-web.exe"):
            require_machine(work / name, machine)
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, work)
        tauri = str(GUI / "node_modules/.bin/tauri.cmd")
        # The CLI supports bundleVCRuntime. The Rust-side config parser on
        # this branch predates it, so pass the setting only to the bundler.
        native_config = work / "build.json"
        native_config.write_text(json.dumps({"version": version}), encoding="utf-8")
        run(tauri, "build", "--no-bundle", "--config", str(native_config), "--", "--locked",
            cwd=GUI, env=env)
        release = TAURI / "target/release"
        require_machine(release / "loushang-gui.exe", machine)

        failures = []
        for package_format in formats:
            try:
                bundle_installer(tauri, work, release, env, args.output,
                                 package_format, facts, product_wheel)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                if args.format != "all":
                    raise
                failures.append(package_format)
                print(f"{package_format} failed: {error}", flush=True)
        if failures:
            raise SystemExit(f"Failed to bundle: {', '.join(failures)}")



if __name__ == "__main__":
    main()
