from __future__ import annotations

import os
import runpy
from collections.abc import Callable


def test_tui_platform_profiles_keep_shared_and_host_paths_disjoint() -> None:
    namespace = runpy.run_path(
        "scripts/run_tui_platform_tests.py",
        run_name="__test__",
    )
    profile_test_paths = namespace["profile_test_paths"]
    assert isinstance(profile_test_paths, Callable)

    shared = set(profile_test_paths("shared"))
    posix = set(profile_test_paths("posix"))
    windows = set(profile_test_paths("windows"))

    assert shared.isdisjoint(posix)
    assert shared.isdisjoint(windows)
    assert posix.isdisjoint(windows)
    assert "tests/tui/test_terminal_platform_darwin.py" in shared
    assert "tests/tui/test_terminal_input_posix.py" in posix
    assert "tests/tui/test_terminal_input_windows.py" in windows


def test_current_tui_platform_profile_selects_only_the_current_host() -> None:
    namespace = runpy.run_path(
        "scripts/run_tui_platform_tests.py",
        run_name="__test__",
    )
    profile_test_paths = namespace["profile_test_paths"]

    current = set(profile_test_paths("current"))
    posix = set(profile_test_paths("posix"))
    windows = set(profile_test_paths("windows"))

    if os.name == "nt":
        assert windows <= current
        assert current.isdisjoint(posix)
    else:
        assert posix <= current
        assert current.isdisjoint(windows)
