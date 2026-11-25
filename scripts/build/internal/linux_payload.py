"""Stage the Full Linux installation payload."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

from internal.common import PYTHON, ROOT, digest, run, wheel
from native_tools import gui_binary
from stage_linux_program import stage_runtime


def stage_payload(package: Path, work: Path, facts: dict) -> dict:
    native = gui_binary(ROOT / "gui/src-tauri/target/release")
    package.mkdir(parents=True)
    product_wheel = wheel(work)
    stage_runtime(package, product_wheel, python_version=PYTHON)
    (package / "bin").mkdir()
    shutil.copy2(native, package / "bin/harness-gui")
    shutil.copy2(native.with_name("loushang-web"), package / "bin/loushang-web")
    shutil.copytree(ROOT / "gui/dist", package / "web")
    launcher = package / "loushang"
    rustc = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
    run(
        rustc,
        "+1.98.1",
        "--edition=2021",
        "-Dwarnings",
        "-O",
        "-C",
        "relocation-model=static",
        "-C",
        "link-arg=-no-pie",
        str(ROOT / "scripts/build/internal/linux_entry.rs"),
        "-o",
        str(launcher),
    )
    launcher.chmod(0o755)
    for name in ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]:
        shutil.copy2(ROOT / name, package / name)
    manifest = {
        **facts,
        "python": run(str(package / "runtime/bin/python3"), "--version"),
        "buildSystem": platform.platform(),
        "guiSha256": digest(native),
        "entrySha256": digest(launcher),
        "wheelSha256": digest(product_wheel),
        "lockSha256": digest(ROOT / "uv.lock"),
    }
    return manifest
