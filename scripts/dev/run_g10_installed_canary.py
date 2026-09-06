#!/usr/bin/env python3
"""Exercise the exact installed G10 command against one native backend."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

_REPORT_FIELDS = {
    "attemptFingerprint",
    "code",
    "hostingBackendId",
    "hostingTransitions",
    "operation",
    "receiptFingerprint",
    "reportVersion",
    "selectionGeneration",
    "state",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-backend",
        required=True,
        choices=("posix-process-group-v1", "windows-job-v1"),
    )
    return parser


def _invoke(
    executable: str,
    operation: str,
    *,
    cwd: Path,
    environ: dict[str, str],
    expected_returncode: int,
) -> dict[str, Any]:
    completed = subprocess.run(
        (
            executable,
            "apphost",
            "canary",
            operation,
            "--format",
            "json",
            "--cwd",
            str(cwd),
        ),
        cwd=cwd,
        env=environ,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != expected_returncode:
        raise RuntimeError(
            f"installed {operation} exit was {completed.returncode}, "
            f"expected {expected_returncode}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"installed {operation} returned invalid JSON") from error
    if not isinstance(value, dict) or set(value) != _REPORT_FIELDS:
        raise RuntimeError(f"installed {operation} returned an invalid report")
    return cast(dict[str, Any], value)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    executable = shutil.which("loushang")
    if executable is None:
        raise RuntimeError("installed loushang console script is unavailable")
    with tempfile.TemporaryDirectory(prefix="loushang-g10-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        environ = dict(os.environ)
        environ["LOUSHANG_HOME"] = str(home)
        status = _invoke(
            executable,
            "status",
            cwd=root,
            environ=environ,
            expected_returncode=0,
        )
        if (status["state"], status["selectionGeneration"]) != (
            "unconfigured",
            0,
        ):
            raise RuntimeError("installed status did not begin fail-closed")
        enabled = _invoke(
            executable,
            "enable",
            cwd=root,
            environ=environ,
            expected_returncode=0,
        )
        run = _invoke(
            executable,
            "run",
            cwd=root,
            environ=environ,
            expected_returncode=0,
        )
        if run["state"] != "ready" or run["hostingBackendId"] != args.expected_backend:
            raise RuntimeError(
                "installed run did not reach the expected native backend"
            )
        if not {"published", "exited", "closed"}.issubset(run["hostingTransitions"]):
            raise RuntimeError("installed run did not settle the native process")
        rolled_back = _invoke(
            executable,
            "rollback",
            cwd=root,
            environ=environ,
            expected_returncode=0,
        )
        denied = _invoke(
            executable,
            "run",
            cwd=root,
            environ=environ,
            expected_returncode=1,
        )
        if not (
            enabled["selectionGeneration"] == 1
            and rolled_back["selectionGeneration"] == 2
            and denied["code"] == "coding_apphost_canary_disabled"
        ):
            raise RuntimeError("installed rollback did not fence the next run")
    print(f"G10 installed canary passed: backend={args.expected_backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
