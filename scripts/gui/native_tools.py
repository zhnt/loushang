"""Host executable naming for opt-in native GUI evidence tools."""

from pathlib import Path
from shutil import which
from sysconfig import get_config_var


def native_binary(directory: Path, name: str) -> Path:
    return directory / (name + (get_config_var("EXE") or ""))


def cargo_path() -> Path:
    installed = native_binary(Path.home() / ".cargo/bin", "cargo")
    return installed if installed.is_file() else Path(which("cargo") or "cargo")
