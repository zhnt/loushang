"""Build a deterministic Linux H6 launcher candidate from checked-in source.

The output is release input, not a Product native profile catalog or Worker
activation authority. Release admission must pin its exact binary digest.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)
from loushang.harness.worker.native_executable_format import (
    verify_worker_native_executable_format,
)

_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src/loushang/hosting/native/contained_launcher_linux_x86_64.c"
)
_FLAGS = (
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-static",
    "-O2",
    "-s",
    "-no-pie",
    "-Wl,--build-id=none",
)


def build(output_dir: Path, *, compiler: str = "cc") -> dict[str, object]:
    """Compile twice and publish only byte-identical native release inputs."""

    if sys.platform != "linux" or platform.machine().lower() not in {
        "x86_64",
        "amd64",
    }:
        raise RuntimeError("Linux x86-64 is required")
    if not _SOURCE.is_file():
        raise FileNotFoundError(_SOURCE)
    executable = shutil.which(compiler)
    if executable is None:
        raise FileNotFoundError(f"C compiler is unavailable: {compiler}")
    destination = output_dir.expanduser().absolute()
    if destination.exists():
        raise FileExistsError(destination)
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    source_digest = sha256(_SOURCE.read_bytes()).hexdigest()
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "SOURCE_DATE_EPOCH": "0", "TZ": "UTC"})
    with tempfile.TemporaryDirectory(prefix="loushang-h6-build-", dir=parent) as work:
        stage = Path(work)
        built: list[bytes] = []
        for name in ("first", "second"):
            binary = stage / name
            command = (
                executable,
                *_FLAGS,
                f'-DLOUSHANG_PROFILE_SHA256="{source_digest}"',
                "-o",
                str(binary),
                str(_SOURCE),
            )
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "Linux H6 launcher build failed: "
                    + completed.stderr.decode("utf-8", errors="replace")
                )
            built.append(binary.read_bytes())
        if built[0] != built[1]:
            raise RuntimeError("Linux H6 launcher build is not reproducible")
        verify_worker_native_executable_format(built[0], platform="linux-x86_64")
        manifest: dict[str, object] = {
            "catalogVersion": 1,
            "platform": "linux-x86_64",
            "profileSourceSha256": source_digest,
            "launcherSha256": sha256(built[0]).hexdigest(),
            "launcherFile": "containment-launcher",
            "buildFlags": list(_FLAGS),
        }
        release = stage / "release"
        release.mkdir(mode=0o700)
        launcher = release / "containment-launcher"
        launcher.write_bytes(built[0])
        launcher.chmod(0o500)
        (release / "catalog.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        source_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        target_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            _rename_directory_noreplace(
                source_fd, release.name, target_fd, destination.name
            )
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
            os.close(source_fd)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", default="cc")
    args = parser.parse_args(argv)
    try:
        manifest = build(args.output_dir, compiler=args.compiler)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Linux H6 launcher build refused: {exc}\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
