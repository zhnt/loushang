from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

SHARED_TEST_PATHS = (
    "tests/tui/test_import_boundaries.py",
    "tests/tui/test_terminal_capabilities.py",
    "tests/tui/test_terminal_diagnostics.py",
    "tests/tui/test_terminal_platform.py",
    "tests/tui/test_terminal_platform_darwin.py",
    "tests/tui/test_terminal_session.py",
    "tests/tui/test_terminal_input.py",
    "tests/tui/test_tui_native_test_runner.py",
    "tests/tui/test_tui_platform_test_runner.py",
)
POSIX_TEST_PATHS = (
    "tests/tui/test_terminal_input_posix_backend.py",
    "tests/tui/test_terminal_input_posix.py",
)
WINDOWS_TEST_PATHS = (
    "tests/tui/test_terminal_input_windows.py",
    "tests/tui/test_terminal_platform_windows.py",
)


def profile_test_paths(profile: str) -> tuple[str, ...]:
    if profile == "shared":
        return SHARED_TEST_PATHS
    if profile == "posix":
        return POSIX_TEST_PATHS
    if profile == "windows":
        return WINDOWS_TEST_PATHS
    if profile == "current":
        host_paths = WINDOWS_TEST_PATHS if os.name == "nt" else POSIX_TEST_PATHS
        return (*SHARED_TEST_PATHS, *host_paths)
    raise ValueError(f"unknown TUI platform test profile: {profile}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one isolated TUI terminal-platform unit-test profile."
    )
    parser.add_argument(
        "profile",
        choices=("shared", "posix", "windows", "current"),
    )
    args, pytest_args = parser.parse_known_args(argv)
    runner = Path(__file__).resolve().parent / "dev" / "run_pytest.py"
    return subprocess.run(
        [
            sys.executable,
            str(runner),
            *profile_test_paths(args.profile),
            "--strict-markers",
            "--strict-config",
            *pytest_args,
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
