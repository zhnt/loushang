"""Stage one independently runnable Linux program from fresh build inputs."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_DIRECTORY = r"""#!/bin/sh
set -eu
directory=${0%/*}
if [ "$directory" = "$0" ]; then directory=.; fi
directory=$(CDPATH= cd -- "$directory" && pwd -P)
"""

_HOST = (
    _DIRECTORY
    + r"""
case ${1:-} in
  start) shift; exec "$directory/runtime/bin/python3" -I -m loushang.coding.cli.lmux server start "$@" ;;
  status|stop) exec "$directory/runtime/bin/python3" -I -m loushang.coding.cli.lmux "$@" ;;
  web) shift; exec "$directory/runtime/bin/python3" -I -m loushang.coding.web_server "$@" ;;
  -h|--help) printf '%s\n' 'Usage: loushang-host {start|status|stop|web} [arguments]'; exit 0 ;;
  *) printf '%s\n' 'Usage: loushang-host {start|status|stop|web} [arguments]' >&2; exit 2 ;;
esac
"""
)

_GUI = (
    _DIRECTORY
    + r"""
unset PYTHONPATH PYTHONHOME
export LOUSHANG_GUI_PYTHON="$directory/runtime/bin/python3"
exec "$directory/bin/harness-gui" "$@"
"""
)


def stage_runtime(package: Path, wheel: Path) -> None:
    python = subprocess.check_output(
        ["uv", "python", "find", "--system", "--managed-python", "3.11"],
        cwd=ROOT,
        text=True,
    ).strip()
    prefix = Path(
        subprocess.check_output(
            [python, "-I", "-c", "import sys; print(sys.base_prefix)"],
            text=True,
        ).strip()
    )
    runtime = package / "runtime"
    shutil.copytree(prefix, runtime, symlinks=True)
    python_lib = runtime / "lib/python3.11"
    (python_lib / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    sites = python_lib / "site-packages"
    if sites.exists():
        shutil.rmtree(sites)
    sites.mkdir()
    requirements = package / "requirements.lock.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    install = ["uv", "pip", "install", "--python", str(runtime / "bin/python3")]
    subprocess.run(install + ["--require-hashes", "-r", str(requirements)], check=True)
    subprocess.run(install + ["--no-deps", str(wheel)], check=True)
    # Only the bundled interpreter is used by our relative-path launchers.
    for entry in (runtime / "bin").iterdir():
        if entry.name not in {"python", "python3", "python3.11"}:
            entry.unlink()
    for entry in runtime.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(runtime):
            raise ValueError(f"Runtime symlink escapes the program directory: {entry}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", choices=("host", "gui"))
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--native", type=Path, help="Tauri release binary for the GUI")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        parser.error("this recipe targets Linux x86_64")
    if (args.program == "gui") != (args.native is not None):
        parser.error("--native is required for GUI and only applies to GUI")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=output.parent) as temporary:
        package = Path(temporary) / "program"
        package.mkdir()
        stage_runtime(package, args.wheel.resolve(strict=True))
        entry = package / f"loushang-{args.program}"
        entry.write_text(_HOST if args.program == "host" else _GUI)
        entry.chmod(0o755)
        if args.native:
            (package / "bin").mkdir()
            shutil.copy2(args.native.resolve(strict=True), package / "bin/harness-gui")
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, package / name)
        package.rename(output)
    print(output)


if __name__ == "__main__":
    main()
