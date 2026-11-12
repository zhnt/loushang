"""Wrap a freshly built full portable runtime in a Debian desktop test package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/deb")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commit = run("git", "rev-parse", "HEAD")
    version = json.loads((ROOT / "gui/package.json").read_text())["version"]
    version += "+gui." + commit[:9]
    target = output / f"loushang_{version}_amd64.deb"
    if target.exists():
        parser.error(f"refusing to overwrite {target}")
    with tempfile.TemporaryDirectory(prefix="loushang-deb-build-") as directory:
        work = Path(directory)
        run(
            "uv",
            "run",
            "--no-project",
            "--python",
            sys.executable,
            "python",
            str(ROOT / "scripts/gui/build_linux_portable.py"),
            "--output",
            str(work / "portable"),
        )
        stage = work / "stage"
        package = stage / "opt/loushang"
        package.parent.mkdir(parents=True)
        shutil.move(str(work / "portable/loushang-linux-x86_64"), package)
        shutil.copy2(
            ROOT / "scripts/gui/tui_appclient_entry.py",
            package / "tui_appclient_entry.py",
        )
        # The portable GUI already contains the Rust Web binary and web/ assets.
        manifest_file = package / "manifest.json"
        manifest = json.loads(manifest_file.read_text())
        manifest.update(
            format="loushang-linux-deb/v1",
            version=version,
        )
        (package / "README.txt").write_text(
            "Loushang desktop test package: GUI, tray, Web assets, CPython, AppHost,\n"
            "AppService, product runtime and locked Python dependencies.\n"
            "Open Loushang in the application menu and start the AppHost from the GUI.\n"
            "GUI close/quit leaves the Host running. Stop it before replacing/removing\n"
            "this test package. Existing settings and Session data remain in user storage.\n"
            "loushang-tui service also controls AppHost. Attach with a named Mux.\n"
            "loushang-mux service controls the installed systemd user unit.\n"
            "Installation leaves the user service disabled and stopped.\n"
            "Ubuntu 26.10 amd64 candidate; other distributions have not been validated.\n"
            "Provider credentials and optional external tools are not included.\n"
        )
        (stage / "usr/bin").mkdir(parents=True)
        (stage / "usr/bin/loushang").symlink_to("../../opt/loushang/loushang")
        install_command(
            stage, package, "loushang-tui", '"$package/tui_appclient_entry.py"'
        )
        install_command(stage, package, "loushang-mux", "-m loushang.coding.cli.mux")
        manifest["managerSha256"] = hashlib.sha256((package / "loushang-mux").read_bytes()).hexdigest()
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
        # Derive ABI requirements from all native payloads, including Python
        # extensions. Private bundled libraries have no Debian shlibs metadata.
        (work / "debian").mkdir()
        (work / "debian/control").write_text(
            "Source: loushang\n\nPackage: loushang\nArchitecture: amd64\n"
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
            f"Package: loushang\nVersion: {version}\nArchitecture: amd64\n"
            "Maintainer: Loushang Contributors <noreply@loushang.ai>\n"
            f"Depends: {depends}\nInstalled-Size: {size}\nSection: devel\nPriority: optional\n"
            "Description: Loushang desktop, terminal, Web and AppHost backend\n"
            " Includes a Python runtime and a systemd user unit for AppHost.\n"
        )
        run("desktop-file-validate", str(desktop))
        run("dpkg-deb", "--root-owner-group", "--build", str(stage), str(target))
    target.with_suffix(".deb.sha256").write_text(
        f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}\n"
    )
    print(target)


if __name__ == "__main__":
    main()
