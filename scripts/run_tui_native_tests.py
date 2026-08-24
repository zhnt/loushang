from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import pytest

SHARED_TEST_PATHS = (
    "tests/tui/test_terminal_query_responder.py",
    "tests/tui/test_terminal_process_backend.py",
    "tests/coding/test_cli_terminal_contract.py",
)
POSIX_TEST_PATHS = (
    "tests/tui/test_terminal_process_backend_posix.py",
    "tests/coding/test_cli_terminal_contract_posix.py",
)
WINDOWS_TEST_PATHS = (
    "tests/tui/test_terminal_process_backend_windows.py",
    "tests/coding/test_cli_terminal_contract_windows.py",
)


def host_profile() -> str:
    return "windows" if os.name == "nt" else "posix"


def profile_test_paths(profile: str) -> tuple[str, ...]:
    if profile == "shared":
        return SHARED_TEST_PATHS
    if profile == "posix":
        return POSIX_TEST_PATHS
    if profile == "windows":
        return WINDOWS_TEST_PATHS
    raise ValueError(f"unknown TUI native test profile: {profile}")


def selected_test_paths(profile: str) -> tuple[str, ...]:
    selected_profile = host_profile() if profile == "current" else profile
    if selected_profile != host_profile():
        raise RuntimeError(
            f"native profile {selected_profile!r} cannot run on {host_profile()!r}"
        )
    return (
        *profile_test_paths("shared"),
        *profile_test_paths(selected_profile),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the shared and host-specific native terminal contracts."
    )
    parser.add_argument(
        "profile",
        choices=("posix", "windows", "current"),
    )
    args, pytest_args = parser.parse_known_args(argv)
    try:
        test_paths = selected_test_paths(args.profile)
    except RuntimeError as error:
        parser.error(str(error))
    return pytest.main(
        [
            *test_paths,
            "--strict-markers",
            "--strict-config",
            *pytest_args,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
