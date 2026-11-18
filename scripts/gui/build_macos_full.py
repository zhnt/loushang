"""Build an Intel macOS 12+ full .pkg with GUI, Web, TUI and AppHost."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = "x86_64-apple-darwin"
MINIMUM = "12.0"
PYINSTALLER = "pyinstaller==6.22.3"


def run(*command: str, cwd: Path = ROOT) -> str:
    print("+ " + shlex.join(command), flush=True)
    try:
        return subprocess.check_output(command, cwd=cwd, text=True).strip()
    except subprocess.CalledProcessError as error:
        print(error.output, file=sys.stderr)
        raise


def audit_native(root: Path) -> list[dict[str, object]]:
    """Check the Intel slice of every shipped Mach-O, including dependencies."""
    report = []
    magics = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
              b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in magics:
                continue
        architectures = run("/usr/bin/lipo", "-archs", str(path)).split()
        if "x86_64" not in architectures:
            raise RuntimeError(f"Intel slice missing: {path.relative_to(root)}")
        load = run("/usr/bin/otool", "-arch", "x86_64", "-l", str(path))
        versions = re.findall(r"\bminos\s+(\d+(?:\.\d+){1,2})", load)
        versions += re.findall(r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+(?:\.\d+){1,2})", load)
        if any(tuple(map(int, value.split(".")[:2])) > (12, 0) for value in versions):
            raise RuntimeError(f"Requires newer macOS: {path.relative_to(root)}: {versions}")
        linked = run("/usr/bin/otool", "-arch", "x86_64", "-L", str(path))
        for library in re.findall(r"^\s+(/\S+)\s+\(", linked, re.MULTILINE):
            if not library.startswith(("/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Unbundled native dependency: {path.relative_to(root)}: {library}")
        report.append({"path": str(path.relative_to(root)), "architectures": architectures,
                       "minimumVersions": versions})
    if not report:
        raise RuntimeError("No native programs found in payload")
    return report


def stage_runtime(resources: Path, wheel: Path, work: Path) -> Path:
    python = run("uv", "python", "find", "--managed-python", "3.11")
    prefix = Path(run(python, "-I", "-c", "import sys; print(sys.base_prefix)"))
    runtime = resources / "runtime"
    shutil.copytree(prefix, runtime, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    library = runtime / "lib/python3.11"
    (library / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    sites = library / "site-packages"
    if sites.exists():
        shutil.rmtree(sites)
    sites.mkdir()
    requirements = work / "requirements.txt"
    run("uv", "export", "--locked", "--no-dev", "--no-emit-project", "--output-file", str(requirements))
    bundled = runtime / "bin/python3"
    install = ["uv", "pip", "install", "--python", str(bundled), "--python-platform", TARGET]
    run(*install, "--require-hashes", "--only-binary", ":all:", "-r", str(requirements))
    run(*install, "--no-deps", str(wheel))
    for entry in (runtime / "bin").iterdir():
        if entry.name not in {"python", "python3", "python3.11"}:
            entry.unlink()
    for entry in runtime.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(runtime):
            raise RuntimeError(f"Runtime has an external symlink: {entry}")
    return bundled


def launcher(path: Path, module: str) -> None:
    path.write_text(
        '#!/bin/sh\nset -eu\n'
        'script=$0\n'
        'while [ -L "$script" ]; do\n'
        '  directory=$(CDPATH= cd -- "$(dirname -- "$script")" && pwd -P)\n'
        '  target=$(/usr/bin/readlink "$script")\n'
        '  case "$target" in /*) script=$target ;; *) script=$directory/$target ;; esac\n'
        'done\n'
        'directory=$(CDPATH= cd -- "$(dirname -- "$script")" && pwd -P)\n'
        'unset PYTHONHOME PYTHONPATH\n'
        f'exec "$directory/../Resources/runtime/bin/python3" -I -m {module} "$@"\n'
    )
    path.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/macos-full")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        parser.error("run this recipe on an Intel Mac")
    os.environ["MACOSX_DEPLOYMENT_TARGET"] = MINIMUM
    os.environ["RUSTUP_TOOLCHAIN"] = "1.98.1"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commit = run("git", "rev-parse", "HEAD")
    version = json.loads((ROOT / "gui/package.json").read_text())["version"]
    destination = output / f"loushang_{version}_{commit[:9]}_macos12_x86_64.pkg"
    if destination.exists():
        parser.error(f"refusing to overwrite {destination}")
    with tempfile.TemporaryDirectory(prefix="loushang-macos-") as directory:
        work = Path(directory)
        config = work / "tauri-macos.json"
        config.write_text(json.dumps({"bundle": {"macOS": {"minimumSystemVersion": MINIMUM}}}))
        run("npm", "ci", cwd=ROOT / "gui")
        run("cargo", "build", "--locked", "--release", "--target", TARGET,
            "--manifest-path", str(ROOT / "gui/web/Cargo.toml"))
        run("npm", "exec", "--", "tauri", "build", "--target", TARGET,
            "--bundles", "app", "--config", str(config), cwd=ROOT / "gui")
        payload = work / "payload"
        app = payload / "Applications/loushang-gui.app"
        app.parent.mkdir(parents=True)
        source = ROOT / f"gui/src-tauri/target/{TARGET}/release/bundle/macos/loushang-gui.app"
        shutil.copytree(source, app, symlinks=True)
        binaries = app / "Contents/MacOS"
        resources = app / "Contents/Resources"
        resources.mkdir(exist_ok=True)
        run("uv", "build", "--wheel", "--out-dir", str(work / "wheels"))
        wheel = next((work / "wheels").glob("loushang-*.whl"))
        stage_runtime(resources, wheel, work)
        shutil.copytree(ROOT / "gui/dist", resources / "web")
        shutil.copy2(ROOT / f"gui/web/target/{TARGET}/release/loushang-web", binaries)
        launcher(binaries / "loushang-mux", "loushang.coding.cli.mux")
        launcher(binaries / "loushang-host", "loushang.coding.foreground_host")
        # Freeze the existing terminal application, not the GUI bridge.
        venv = work / "tui-venv"
        run("uv", "venv", "--python", "3.11", str(venv))
        python = str(venv / "bin/python")
        requirements = str(work / "requirements.txt")
        run("uv", "pip", "install", "--python", python, "--python-platform", TARGET,
            "--require-hashes", "--only-binary", ":all:", "-r", requirements)
        run("uv", "pip", "install", "--python", python, "--no-deps", str(wheel))
        run("uv", "pip", "install", "--python", python, "--python-platform", TARGET, PYINSTALLER)
        run(python, "-m", "PyInstaller", "--noconfirm", "--distpath", str(binaries),
            "--workpath", str(work / "tui-build"), str(ROOT / "loushang.spec"))
        commands = payload / "usr/local/bin"
        commands.mkdir(parents=True)
        for name in ("loushang", "loushang-gui", "loushang-mux", "loushang-host", "loushang-web"):
            (commands / name).symlink_to(f"/Applications/loushang-gui.app/Contents/MacOS/{name}")
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, resources)
        native = audit_native(app)
        manifest = {"format": "loushang-macos-full/v1", "commit": commit,
                    "architecture": TARGET, "minimumSystemVersion": MINIMUM,
                    "signedForDistribution": False, "nativeFiles": native}
        (resources / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for record in native:
            run("/usr/bin/codesign", "--force", "--sign", "-", str(app / str(record["path"])))
        run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app))
        components = work / "components.plist"
        run("/usr/bin/pkgbuild", "--analyze", "--root", str(payload), str(components))
        entries = plistlib.loads(components.read_bytes())
        for entry in entries:
            entry["BundleIsRelocatable"] = False
        components.write_bytes(plistlib.dumps(entries))
        component = work / "full.pkg"
        run("/usr/bin/pkgbuild", "--root", str(payload), "--component-plist", str(components),
            "--install-location", "/", "--identifier", "ai.loushang.full", "--version", version,
            str(component))
        requirements_plist = work / "requirements.plist"
        requirements_plist.write_bytes(plistlib.dumps({"os": [MINIMUM], "arch": ["x86_64"]}))
        run("/usr/bin/productbuild", "--product", str(requirements_plist),
            "--package", str(component), str(destination))
        shutil.copy2(resources / "manifest.json", output / (destination.stem + ".manifest.json"))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".pkg.sha256").write_text(f"{digest}  {destination.name}\n")
    print(destination)


if __name__ == "__main__":
    main()
