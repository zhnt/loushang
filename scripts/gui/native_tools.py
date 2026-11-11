"""Executable naming for native GUI build and acceptance tools."""

import json
from pathlib import Path
from shutil import which
from sysconfig import get_config_var


def native_binary(directory: Path, name: str) -> Path:
    return directory / (name + (get_config_var("EXE") or ""))


def gui_binary(directory: Path) -> Path:
    config = Path(__file__).resolve().parents[2] / "gui/src-tauri/tauri.conf.json"
    return native_binary(
        directory, json.loads(config.read_text(encoding="utf-8"))["mainBinaryName"]
    )


def cargo_path() -> Path:
    installed = native_binary(Path.home() / ".cargo/bin", "cargo")
    return installed if installed.is_file() else Path(which("cargo") or "cargo")
