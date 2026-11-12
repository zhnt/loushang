"""Build the existing loushang CLI as a single Windows x64 executable."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYINSTALLER = "pyinstaller==6.22.3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/windows-tui")
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().upper() != "AMD64":
        parser.error("this recipe targets Windows x64")
    target = args.output.resolve() / "loushang.exe"
    if target.exists():
        parser.error(f"refusing to overwrite {target}")

    with tempfile.TemporaryDirectory(prefix="loushang-tui-") as directory:
        work = Path(directory)
        venv = work / "venv"
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)}
        subprocess.run(
            ["uv", "sync", "--locked", "--no-dev", "--no-editable", "--python", "3.11",
             "--managed-python"],
            cwd=ROOT, env=env, check=True,
        )
        python = str(venv / "Scripts/python.exe")
        subprocess.run(["uv", "pip", "install", "--python", python, PYINSTALLER],
                       cwd=ROOT, check=True)
        entry = work / "entry.py"
        entry.write_text(
            "from loushang.coding.cli.__main__ import main\n"
            "raise SystemExit(main())\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                python, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
                "--name", "loushang", "--collect-submodules", "loushang",
                "--collect-data", "loushang", "--copy-metadata", "loushang", str(entry),
            ],
            cwd=work, check=True,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as destination, (work / "dist/loushang.exe").open("rb") as source:
            shutil.copyfileobj(source, destination)
    print(target)


if __name__ == "__main__":
    main()
