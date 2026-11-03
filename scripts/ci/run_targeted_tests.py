"""Run a selector-produced batch of repository test paths without shell parsing."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_KEY = "TARGET_TEST_PATHS_JSON"


def target_paths(raw: str, *, root: Path = ROOT) -> list[str]:
    try:
        paths = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("target test paths must be JSON") from error
    if (
        not isinstance(paths, list)
        or not paths
        or not all(isinstance(path, str) and path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise ValueError("target test paths must be a nonempty unique string list")
    for path in paths:
        file_path = path.split("::", 1)[0]
        if (
            not file_path.startswith("tests/")
            or Path(file_path).is_absolute()
            or ".." in Path(file_path).parts
            or not (root / file_path).is_file()
        ):
            raise ValueError(f"invalid target test path: {path}")
    return paths


def main() -> int:
    try:
        paths = target_paths(os.environ.get(ENVIRONMENT_KEY, ""))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    return subprocess.run(
        [
            sys.executable,
            "scripts/dev/run_pytest.py",
            *paths,
            "-m",
            "not live",
            "--strict-markers",
            "-q",
        ],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
