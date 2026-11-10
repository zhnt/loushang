"""Build a relocatable Linux GUI + Python/AppHost candidate, without user data."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

from native_tools import gui_binary

ROOT = Path(__file__).resolve().parents[2]


def run(*command: str) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/desktop")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("this packaging recipe targets Linux x86_64")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = output / "loushang-linux-x86_64"
    if package.exists():
        parser.error(f"refusing to overwrite existing package: {package}")
    native = gui_binary(ROOT / "gui/src-tauri/target/release")
    if not native.is_file():
        parser.error("run npm --prefix gui run build first")
    python = run("uv", "python", "find", "--system", "--managed-python", "3.11")
    prefix = Path(run(python, "-I", "-c", "import sys; print(sys.base_prefix)"))
    package.mkdir()
    shutil.copytree(prefix, package / "runtime", symlinks=True)
    # Only the private copied runtime is ours to populate, never the managed
    # interpreter from which it was copied.
    (package / "runtime/lib/python3.11/EXTERNALLY-MANAGED").unlink(missing_ok=True)
    # Never inherit packages installed into the build interpreter.
    sites = package / "runtime/lib/python3.11/site-packages"
    if sites.exists():
        shutil.rmtree(sites)
    sites.mkdir(parents=True)
    bundled_python = package / "runtime/bin/python3"
    requirements = run("uv", "export", "--locked", "--no-dev", "--no-emit-project")
    (package / "requirements.lock.txt").write_text(requirements + "\n")
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(bundled_python),
        "--require-hashes",
        "--requirements",
        str(package / "requirements.lock.txt"),
    )
    wheels = output / "wheels"
    run("uv", "build", "--wheel", "--out-dir", str(wheels))
    wheel = next(wheels.glob("loushang-*.whl"))
    run(
        "uv", "pip", "install", "--python", str(bundled_python), "--no-deps", str(wheel)
    )
    # Console-script shebangs contain the staging path. The package entry point
    # invokes modules with its own interpreter instead of shipping broken tools.
    for entry in (package / "runtime/bin").iterdir():
        if entry.name not in {"python", "python3", "python3.11"}:
            entry.unlink()
    for entry in package.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(package):
            raise RuntimeError(f"external symlink in portable runtime: {entry}")
    (package / "bin").mkdir()
    shutil.copy2(native, package / "bin/harness-gui")
    shutil.copy2(
        ROOT / "scripts/gui/desktop_launcher.py", package / "desktop_launcher.py"
    )
    launcher = package / "loushang"
    rustc = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
    run(
        rustc,
        "+1.98.1",
        "--edition=2021",
        "-Dwarnings",
        "-O",
        "-C",
        "relocation-model=static",
        "-C",
        "link-arg=-no-pie",
        str(ROOT / "scripts/gui/portable_entry.rs"),
        "-o",
        str(launcher),
    )
    launcher.chmod(0o755)
    for name in ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]:
        shutil.copy2(ROOT / name, package / name)
    shutil.copy2(ROOT / "scripts/gui/portable_README.txt", package / "README.txt")
    manifest = {
        "format": "loushang-linux-portable/v1",
        "commit": run("git", "rev-parse", "HEAD"),
        "python": run(str(bundled_python), "--version"),
        "buildSystem": platform.platform(),
        "guiSha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "entrySha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "launcherSha256": hashlib.sha256(
            (package / "desktop_launcher.py").read_bytes()
        ).hexdigest(),
        "wheelSha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "lockSha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    }
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = output / (package.name + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(package, arcname=package.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n"
    )
    print(f"Built {archive} ({archive.stat().st_size // 1024 // 1024} MiB)")


if __name__ == "__main__":
    main()
