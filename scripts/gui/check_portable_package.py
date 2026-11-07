"""Opt-in real packaged AppHost lifecycle test; no provider requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    env = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONPATH": "/nonexistent"}
    with tempfile.TemporaryDirectory(prefix="loushang-package-check-") as temp:
        root = Path(temp)
        workspace = root / "workspace with spaces"
        workspace.mkdir()
        command = [
            str(package / "loushang"),
            "--workspace",
            str(workspace),
            "--state-root",
            str(root / "state"),
        ]

        def call(*flags: str, check: bool = True) -> subprocess.CompletedProcess:
            return subprocess.run(
                command + list(flags),
                cwd=workspace,
                env=env,
                text=True,
                capture_output=True,
                timeout=70,
                check=check,
            )

        location = subprocess.check_output(
            [
                str(package / "runtime/bin/python3"),
                "-I",
                "-c",
                "import loushang,sys; print(loushang.__file__); print(sys.prefix)",
            ],
            cwd=workspace,
            env=env,
            text=True,
        ).splitlines()
        assert all(Path(item).is_relative_to(package) for item in location), location
        try:
            call("--start-only")
            first = json.loads(call("--status").stdout)
            assert len(first["muxes"]) == 1 and first["muxes"][0]["name"] == "desktop"
            records = list((root / "state").glob("*/connection/*"))
            fingerprints = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in records
                if p.is_file()
            }
            assert fingerprints
            call("--start-only")
            assert json.loads(call("--status").stdout) == first
            assert fingerprints == {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in records
                if p.is_file()
            }
            call("--stop")
            for _ in range(50):
                if call("--status", check=False).returncode:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("AppHost did not stop")
            call("--start-only")
            assert json.loads(call("--status").stdout) == first
            print(
                "PASS: relocated imports, packaged startup, host reuse, stop and retained mux restart"
            )
        finally:
            call("--stop", check=False)
            for _ in range(50):
                if call("--status", check=False).returncode:
                    break
                time.sleep(0.1)


if __name__ == "__main__":
    main()
