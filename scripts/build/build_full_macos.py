"""Build a Full macOS 12+ PKG from the current checkout."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from internal.common import (
    PYINSTALLER,
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

MINIMUM = "12.0"
MAC_ARCH = {"x86_64": ("x86_64", "x64"), "aarch64": ("arm64", "arm64")}


def run(*command: str, cwd: Path = ROOT) -> str:
    print("+ " + shlex.join(command), flush=True)
    try:
        return subprocess.check_output(command, cwd=cwd, text=True).strip()
    except subprocess.CalledProcessError as error:
        print(error.output, file=sys.stderr)
        raise


def audit_native(root: Path, arch: str = "x86_64") -> list[dict[str, object]]:
    """Check the target slice of every shipped Mach-O, including dependencies."""
    report: list[dict[str, object]] = []
    magics = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
              b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in magics:
                continue
        architectures = run("/usr/bin/lipo", "-archs", str(path)).split()
        if arch not in architectures:
            raise RuntimeError(f"Required {arch} slice missing: {path.relative_to(root)}")
        load = run("/usr/bin/otool", "-arch", arch, "-l", str(path))
        versions = re.findall(r"\bminos\s+(\d+(?:\.\d+){1,2})", load)
        versions += re.findall(r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+(?:\.\d+){1,2})", load)
        if any(tuple(map(int, value.split(".")[:2])) > (12, 0) for value in versions):
            raise RuntimeError(f"Requires newer macOS: {path.relative_to(root)}: {versions}")
        linked = run("/usr/bin/otool", "-arch", arch, "-L", str(path))
        # otool -L includes LC_ID_DYLIB before its actual load dependencies.
        # The library's own link-time identity is not an external file load.
        identity = re.search(r"cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.+?) \(offset", load)
        for library in re.findall(r"^\s+(/\S+)\s+\(", linked, re.MULTILINE):
            if identity is not None and library == identity[1]:
                continue
            if not library.startswith(("/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Unbundled native dependency: {path.relative_to(root)}: {library}")
        report.append({"path": str(path.relative_to(root)), "architectures": architectures,
                       "minimumVersions": versions})
    if not report:
        raise RuntimeError("No native programs found in payload")
    return report


def stage_runtime(resources: Path, product_wheel: Path, work: Path, target: str) -> Path:
    python = run("uv", "python", "find", "--system", "--managed-python", PYTHON)
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
    install = ["uv", "pip", "install", "--python", str(bundled), "--python-platform", target]
    run(*install, "--require-hashes", "--only-binary", ":all:", "-r", str(requirements))
    run(*install, "--no-deps", str(product_wheel))
    for entry in (runtime / "bin").iterdir():
        if entry.name not in {"python", "python3", "python3.11"}:
            entry.unlink()
    for entry in runtime.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(runtime):
            raise RuntimeError(f"Runtime has an external symlink: {entry}")
    return bundled


def audit_frozen(python: str, executable: Path, work: Path, arch: str) -> list[dict[str, object]]:
    """Include the native libraries compressed inside the standalone TUI."""
    extracted = work / "frozen-native"
    extracted.mkdir()
    run(python, "-c", """
import sys
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
reader = CArchiveReader(sys.argv[1])
root = Path(sys.argv[2]).resolve()
for name, entry in reader.toc.items():
    if entry[-1] != 'b':
        continue
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('unsafe frozen archive path')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(reader.extract(name))
""", str(executable), str(extracted))
    return audit_native(extracted, arch)


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
    args = arguments(__doc__, "Darwin", ("pkg",))
    arch, label = MAC_ARCH[args.arch]
    target = f"{args.arch}-apple-darwin"
    require_tools("git", "uv", "node", "npm", "cargo", "rustc", "xcodebuild",
                  "codesign", "pkgbuild", "productbuild", "pkgutil")
    run("xcodebuild", "-version")
    facts = provenance()
    version = facts["version"]
    os.environ["MACOSX_DEPLOYMENT_TARGET"] = MINIMUM
    os.environ["RUSTUP_TOOLCHAIN"] = "1.98.1"
    os.environ.pop("CARGO_BUILD_TARGET", None)
    os.environ.pop("CARGO_TARGET_DIR", None)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    run("uv", "python", "install", PYTHON)
    prepare_npm()
    with tempfile.TemporaryDirectory(prefix=".loushang-macos-", dir=output) as directory:
        # macOS tempfile paths can use /var while realpath uses /private/var.
        work = Path(directory).resolve()
        config = work / "tauri-macos.json"
        destination = work / f"loushang-{version}-{label}.pkg"
        config.write_text(json.dumps({"version": version,
                                      "bundle": {"macOS": {"minimumSystemVersion": MINIMUM}}}))
        run("cargo", "build", "--locked", "--release", "--target", target,
            "--manifest-path", str(ROOT / "gui/web/Cargo.toml"))
        run("npm", "exec", "--", "tauri", "build", "--target", target,
            "--bundles", "app", "--config", str(config), "--", "--locked", cwd=ROOT / "gui")
        payload = work / "payload"
        app = payload / "Applications/loushang-gui.app"
        app.parent.mkdir(parents=True)
        source = ROOT / f"gui/src-tauri/target/{target}/release/bundle/macos/loushang-gui.app"
        shutil.copytree(source, app, symlinks=True)
        binaries = app / "Contents/MacOS"
        resources = app / "Contents/Resources"
        resources.mkdir(exist_ok=True)
        product_wheel = wheel(work)
        stage_runtime(resources, product_wheel, work, target)
        shutil.copytree(ROOT / "gui/dist", resources / "web")
        shutil.copy2(ROOT / f"gui/web/target/{target}/release/loushang-web", binaries)
        launcher(binaries / "loushang-mux", "loushang.coding.cli.mux")
        launcher(binaries / "loushang-host", "loushang.coding.hosted.foreground")
        # Freeze the existing terminal application, not the GUI bridge.
        venv = work / "tui-venv"
        run("uv", "venv", "--managed-python", "--python", PYTHON, str(venv))
        python = str(venv / "bin/python")
        requirements = str(work / "requirements.txt")
        run("uv", "pip", "install", "--python", python, "--python-platform", target,
            "--require-hashes", "--only-binary", ":all:", "-r", requirements)
        run("uv", "pip", "install", "--python", python, "--no-deps", str(product_wheel))
        run("uv", "pip", "install", "--python", python, "--python-platform", target, "--only-binary", ":all:", PYINSTALLER)
        run(python, "-m", "PyInstaller", "--noconfirm", "--distpath", str(binaries),
            "--workpath", str(work / "tui-build"), str(ROOT / "loushang.spec"))
        commands = payload / "usr/local/bin"
        commands.mkdir(parents=True)
        for name in ("loushang", "loushang-gui", "loushang-mux", "loushang-host", "loushang-web"):
            (commands / name).symlink_to(f"/Applications/loushang-gui.app/Contents/MacOS/{name}")
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, resources)
        native = audit_native(app, arch)
        frozen_native = audit_frozen(python, binaries / "loushang", work, arch)
        manifest = {"format": "loushang-macos-full/v1", **facts,
                    "wheelSha256": digest(product_wheel), "lockSha256": digest(ROOT / "uv.lock"),
                    "architecture": target, "minimumSystemVersion": MINIMUM,
                    "signedForDistribution": False, "nativeFiles": native,
                    "frozenTuiNativeFiles": frozen_native}
        (resources / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for record in native:
            # Signing the bundle's main executable also validates its siblings.
            # Sign it with the enclosing bundle after all nested code is ready.
            if record["path"] == "Contents/MacOS/loushang-gui":
                continue
            run("/usr/bin/codesign", "--force", "--sign", "-", str(app / str(record["path"])))
        run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        components = work / "components.plist"
        run("/usr/bin/pkgbuild", "--analyze", "--root", str(payload), str(components))
        entries = plistlib.loads(components.read_bytes())
        for entry in entries:
            entry["BundleIsRelocatable"] = False
        components.write_bytes(plistlib.dumps(entries))
        component = work / "full.pkg"
        run("/usr/bin/pkgbuild", "--root", str(payload), "--component-plist", str(components),
            "--scripts", str(Path(__file__).parent / "internal/macos_scripts"),
            "--install-location", "/", "--identifier", "ai.loushang.full", "--version", version,
            str(component))
        requirements_plist = work / "requirements.plist"
        requirements_plist.write_bytes(plistlib.dumps({"os": [MINIMUM], "arch": [arch]}))
        run("/usr/bin/productbuild", "--product", str(requirements_plist),
            "--package", str(component), str(destination))
        expanded = work / "expanded"
        run("/usr/sbin/pkgutil", "--expand", str(destination), str(expanded))
        if not (expanded / "Distribution").is_file():
            raise RuntimeError("Missing PKG Distribution metadata")
        report = work / (destination.stem + ".manifest.json")
        shutil.copy2(resources / "manifest.json", report)
        publish(destination, output)
        report.replace(output / report.name)


if __name__ == "__main__":
    main()
