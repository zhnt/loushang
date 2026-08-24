from __future__ import annotations

import os
import runpy
from collections.abc import Callable


def _runner_namespace() -> dict[str, object]:
    return runpy.run_path(
        "scripts/run_tui_native_tests.py",
        run_name="__test__",
    )


def test_native_profiles_keep_shared_posix_and_windows_files_disjoint() -> None:
    namespace = _runner_namespace()
    profile_test_paths = namespace["profile_test_paths"]
    assert isinstance(profile_test_paths, Callable)

    shared = set(profile_test_paths("shared"))
    posix = set(profile_test_paths("posix"))
    windows = set(profile_test_paths("windows"))

    assert shared.isdisjoint(posix)
    assert shared.isdisjoint(windows)
    assert posix.isdisjoint(windows)
    assert "tests/tui/test_terminal_process_backend.py" in shared
    assert "tests/tui/test_terminal_process_backend_posix.py" in posix
    assert "tests/tui/test_terminal_process_backend_windows.py" in windows
    assert "tests/coding/test_cli_terminal_contract_posix.py" in posix
    assert "tests/coding/test_cli_terminal_contract_windows.py" in windows


def test_current_native_profile_collects_only_the_current_host_contract() -> None:
    namespace = _runner_namespace()
    selected_test_paths = namespace["selected_test_paths"]
    profile_test_paths = namespace["profile_test_paths"]
    assert isinstance(selected_test_paths, Callable)
    assert isinstance(profile_test_paths, Callable)

    current = set(selected_test_paths("current"))
    shared = set(profile_test_paths("shared"))
    posix = set(profile_test_paths("posix"))
    windows = set(profile_test_paths("windows"))

    assert shared <= current
    if os.name == "nt":
        assert windows <= current
        assert current.isdisjoint(posix)
    else:
        assert posix <= current
        assert current.isdisjoint(windows)
