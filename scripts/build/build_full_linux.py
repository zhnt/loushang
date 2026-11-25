"""Build a Full Linux installer from the current checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
    run,
)

# Reuse the GUI binary locator and the runtime staging used by split-program checks.
sys.path.insert(0, str(ROOT / "scripts/gui"))
from internal.linux_payload import stage_payload

INTERNAL = Path(__file__).parent / "internal"


def install_command(stage: Path, package: Path, name: str, python_args: str) -> None:
    launcher = package / name
    launcher.write_text(
        "#!/bin/sh\nset -eu\n"
        'launcher=$(/usr/bin/readlink -f -- "$0")\n'
        "package=${launcher%/*}\n"
        f'exec "$package/runtime/bin/python3" -I {python_args} "$@"\n'
    )
    launcher.chmod(0o755)
    (stage / "usr/bin" / name).symlink_to(f"../../opt/loushang/{name}")


def main() -> None:
    args = arguments(__doc__, "Linux", ("deb", "rpm"))
    distro = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines()
                  if "=" in line)
    expected = "ubuntu" if args.format == "deb" else "fedora"
    minimum = (24, 4) if args.format == "deb" else (43,)
    release = distro.get("VERSION_ID", "").strip('"').split(".")
    if (distro.get("ID", "").strip('"') != expected
            or not all(part.isdecimal() for part in release)
            or tuple(map(int, release)) < minimum):
        raise SystemExit(f"{args.format} requires native {expected} {'.'.join(map(str, minimum))}+")
    require_tools("git", "uv", "node", "npm", "cc", "desktop-file-validate", "pkg-config",
                  *(("dpkg-deb", "dpkg-shlibdeps") if args.format == "deb" else ("rpm", "rpmbuild")))
    run("pkg-config", "--print-errors", "--exists", "webkit2gtk-4.1", "gtk+-3.0", "openssl")
    facts = provenance()
    version = facts["version"]
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[args.arch]
    args.output.mkdir(parents=True, exist_ok=True)
    run("uv", "python", "install", PYTHON)
    # These paths are shared with the normal GUI build; pin the target locations
    # so environment overrides cannot make us package a previous binary.
    os.environ.pop("CARGO_TARGET_DIR", None)
    os.environ.pop("CARGO_BUILD_TARGET", None)
    prepare_npm()
    subprocess.run(["npm", "run", "build"], cwd=GUI, check=True)
    with tempfile.TemporaryDirectory(prefix=".loushang-linux-", dir=args.output) as directory:
        work = Path(directory)
        stage = work / "stage"
        package = stage / "opt/loushang"
        manifest = stage_payload(package, work, facts)
        shutil.copy2(
            ROOT / "scripts/gui/tui_appclient_entry.py",
            package / "tui_appclient_entry.py",
        )
        # Record the exact payload assembled for this installer.
        manifest_file = package / "manifest.json"
        manifest.update(
            format=f"loushang-linux-{args.format}/v1",
            architecture=args.arch,
        )
        (package / "README.txt").write_text(
            "Loushang Full package: GUI, tray, Web assets, CPython, AppHost,\n"
            "AppService, product runtime and locked Python dependencies.\n"
            "Open Loushang in the application menu and start the AppHost from the GUI.\n"
            "GUI close/quit leaves the Host running. Stop it before replacing/removing\n"
            "this package. Existing settings and Session data remain in user storage.\n"
            "loushang-tui service also controls AppHost. Attach with a named Mux.\n"
            "loushang-mux service controls the installed systemd user unit.\n"
            "Fresh installation leaves the user service disabled and stopped.\n"
                        "Provider credentials and optional external tools are not included.\n"
        )
        (stage / "usr/bin").mkdir(parents=True)
        (stage / "usr/bin/loushang").symlink_to("../../opt/loushang/loushang")
        install_command(
            stage, package, "loushang-tui", '"$package/tui_appclient_entry.py"'
        )
        install_command(stage, package, "loushang-mux", "-m loushang.coding.cli.mux")
        manifest["managerSha256"] = digest(package / "loushang-mux")
        manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
        unit = stage / "usr/lib/systemd/user/loushang-host.service"
        unit.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/gui/loushang-host.service", unit)
        desktop = stage / "usr/share/applications/ai.loushang.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(
            "[Desktop Entry]\nType=Application\nName=Loushang\n"
            "Comment=Loushang desktop with bundled backend\nExec=/usr/bin/loushang\n"
            "Icon=ai.loushang.harnessgui\nTerminal=false\nCategories=Development;\n"
        )
        icon = stage / "usr/share/icons/hicolor/128x128/apps/ai.loushang.harnessgui.png"
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "gui/src-tauri/icons/128x128.png", icon)
        run("desktop-file-validate", str(desktop))
        if args.format == "deb":
            target = build_deb(work, stage, package, version, arch)
        else:
            target = build_rpm(work, stage, version, args.arch)
        publish(target, args.output)


def build_deb(work, stage, package, version, arch):
    # Derive ABI requirements from all native payloads, including Python
    # extensions. Private bundled libraries have no Debian shlibs metadata.
    (work / "debian").mkdir()
    (work / "debian/control").write_text(
        f"Source: loushang\n\nPackage: loushang\nArchitecture: {arch}\n"
    )
    native_files = []
    for path in package.rglob("*"):
        # CPython's stable-ABI shim names libpython with $ORIGIN in DT_NEEDED,
        # unsupported by dpkg-shlibdeps. Scan its actual target below instead.
        if path.name == "libpython3.so":
            continue
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    native_files.append(path)
    library_dirs = sorted({str(path.parent) for path in native_files})
    control = stage / "DEBIAN"
    control.mkdir()
    for name in ("preinst", "prerm"):
        shutil.copyfile(INTERNAL / "check_linux_stopped.sh", control / name)
        (control / name).chmod(0o755)
    dependencies = run(
        "dpkg-shlibdeps",
        "-O",
        "--ignore-missing-info",
        *("-l" + path for path in library_dirs),
        *("-e" + str(path) for path in native_files),
        cwd=work,
    )
    depends = next(
        line.removeprefix("shlibs:Depends=")
        for line in dependencies.splitlines()
        if line.startswith("shlibs:Depends=")
    )
    depends += ", libayatana-appindicator3-1, ca-certificates, xdg-utils"
    size = (
        sum(
            p.stat().st_size
            for p in stage.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        // 1024
    )
    (control / "control").write_text(
        f"Package: loushang\nVersion: {version}\nArchitecture: {arch}\n"
        "Maintainer: Loushang Contributors <noreply@loushang.ai>\n"
        f"Depends: {depends}\nInstalled-Size: {size}\nSection: devel\nPriority: optional\n"
        "Description: Loushang desktop, terminal, Web and AppHost backend\n"
        " Includes a Python runtime and a systemd user unit for AppHost.\n"
    )
    target = work / f"loushang_{version}_{arch}.deb"
    run("dpkg-deb", "--root-owner-group", "--build", str(stage), str(target))
    metadata = run("dpkg-deb", "-f", str(target), "Package", "Version", "Architecture")
    if metadata.splitlines() != ["Package: loushang", f"Version: {version}", f"Architecture: {arch}"]:
        raise RuntimeError(f"Unexpected DEB package metadata: {metadata}")
    subprocess.run([sys.executable, str(ROOT / "scripts/gui/check_deb_package.py"), str(target)],
                   check=True)
    return target


def build_rpm(work, stage, version, arch):
    run("rpmbuild", "-bb", "--target", arch, "--define", f"_topdir {work}",
        "--define", f"product_version {version}", "--define", f"payload {stage}",
        "--define", f"guard {INTERNAL / 'check_linux_stopped.sh'}",
        str(INTERNAL / "loushang.spec"))
    (source,) = (work / "RPMS").rglob("*.rpm")
    target = work / source.name
    source.rename(target)
    metadata = run("rpm", "-qp", "--qf", "%{NAME}:%{VERSION}:%{ARCH}", str(target))
    if metadata != f"loushang:{version}:{arch}":
        raise RuntimeError(f"Unexpected RPM package metadata: {metadata}")
    return target


if __name__ == "__main__":
    main()
