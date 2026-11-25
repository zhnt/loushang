"""Freeze the TUI for inclusion in the Windows Full installer."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from internal.common import PYINSTALLER, PYTHON, ROOT


def build_tui(target: Path, wheel: Path, requirements: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="loushang-tui-") as directory:
        work = Path(directory)
        venv = work / "venv"
        subprocess.run(["uv", "venv", "--managed-python", "--python", PYTHON, str(venv)],
                       cwd=ROOT, check=True)
        python = str(venv / "Scripts/python.exe")
        install = ["uv", "pip", "install", "--python", python]
        subprocess.run([*install, "--require-hashes", "--only-binary", ":all:", "-r", str(requirements)],
                       cwd=ROOT, check=True)
        subprocess.run([*install, "--no-deps", str(wheel)], cwd=ROOT, check=True)
        subprocess.run([*install, "--only-binary", ":all:", PYINSTALLER], cwd=ROOT, check=True)
        subprocess.run(
            [
                python, "-m", "PyInstaller", "--noconfirm",
                "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
                str(ROOT / "loushang.spec"),
            ],
            cwd=ROOT, check=True,
        )
        shutil.copy2(work / "dist/loushang.exe", target)
