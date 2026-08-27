from __future__ import annotations

from loushang.harness.environment import resolve_platform_paths


def test_platform_paths_separate_durable_state_and_ephemeral_roots(tmp_path) -> None:
    platform_home = tmp_path / "home"
    runtime = tmp_path / "run"

    paths = resolve_platform_paths(
        environ={
            "LOUSHANG_HOME": str(platform_home),
            "LOUSHANG_RUNTIME_DIR": str(runtime),
        },
        temporary_root=tmp_path / "ignored-tmp",
    )

    assert paths.home == platform_home.resolve()
    assert paths.data == platform_home.resolve() / "data"
    assert paths.state == platform_home.resolve() / "state"
    assert paths.cache == platform_home.resolve() / "cache"
    assert paths.runtime == runtime.resolve()
    assert paths.temporary == runtime.resolve() / "tmp"
    assert not platform_home.exists()
    assert not runtime.exists()


def test_platform_paths_support_independent_temporary_override(tmp_path) -> None:
    temporary = tmp_path / "temporary"

    paths = resolve_platform_paths(
        environ={
            "LOUSHANG_HOME": str(tmp_path / "home"),
            "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
            "LOUSHANG_TMPDIR": str(temporary),
        }
    )

    assert paths.temporary == temporary.resolve()
