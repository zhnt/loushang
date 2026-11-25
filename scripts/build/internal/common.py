"""Shared inputs and final artifact handling for the Full builders."""

from __future__ import annotations

import argparse
import hashlib
import platform
import re
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUI = ROOT / "gui"
PYTHON = (ROOT / ".python-version").read_text().strip()
PYINSTALLER = "pyinstaller==6.22.3"
ARCHITECTURES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


def arguments(description, system, formats, supported=("x86_64", "aarch64")):
    native = ARCHITECTURES.get(platform.machine().lower())
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--arch", choices=("x86_64", "aarch64"), default=native)
    parser.add_argument("--format", choices=formats, default=formats[0])
    parser.add_argument("--output", type=Path, default=ROOT / "dist/packages")
    args = parser.parse_args()
    if platform.system() != system or args.arch != native or native not in supported:
        parser.error(f"requires a native {system} build machine ({', '.join(supported)})")
    args.output = args.output.resolve()
    return args


def require_tools(*names):
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        raise SystemExit(f"Missing build tools: {', '.join(missing)}. See scripts/build/README.md.")


def run(*command, cwd=ROOT):
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def wheel(work):
    directory = work / "wheels"
    # Build through a fresh sdist so setuptools cannot reuse stale build/lib.
    subprocess.run(["uv", "build", "--no-sources", "--out-dir", str(directory)],
                   cwd=ROOT, check=True)
    (result,) = directory.glob("loushang-*.whl")
    return result


def prepare_npm():
    npm = "npm.cmd" if platform.system() == "Windows" else "npm"
    subprocess.run([npm, "run", "doctor"], cwd=GUI, check=True)
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=GUI, check=True)


def version():
    value = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", value):
        raise SystemExit("Full installers require a product version in major.minor.patch form")
    return value


def provenance():
    return {
        "version": version(),
        "commit": run("git", "rev-parse", "HEAD"),
        "dirty": bool(run("git", "status", "--porcelain")),
        "built_at": datetime.now(UTC).isoformat(),
    }


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish(package, output):
    checksum = package.with_name(package.name + ".sha256")
    checksum.write_text(f"{digest(package)}  {package.name}\n", encoding="ascii")
    package.replace(output / package.name)
    checksum.replace(output / checksum.name)
    print(output / package.name, flush=True)
