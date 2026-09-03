from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from loushang.foundation.runtime_scope import RunLease

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/dev/run_pytest.py"
SPEC = importlib.util.spec_from_file_location("run_pytest", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
run_pytest_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_pytest_module
SPEC.loader.exec_module(run_pytest_module)


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "LOUSHANG_HOME": str(tmp_path / "home"),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "LOUSHANG_PYTEST_MIN_FREE_BYTES": "0",
    }


def test_pytest_runtime_scope_is_namespaced_outside_the_checkout(
    tmp_path: Path,
) -> None:
    scope = run_pytest_module.resolve_pytest_runtime_scope(
        environ=_environment(tmp_path),
        run_id="a" * 32,
    )

    assert scope.run_dir == tmp_path / "runtime" / "pytest-runs" / ("a" * 32)


def test_managed_pytest_uses_one_private_root_and_cleans_read_only_content(
    tmp_path: Path,
) -> None:
    observed: list[list[str]] = []
    run_dir: Path | None = None

    def fake_pytest_main(arguments: list[str]) -> int:
        nonlocal run_dir
        observed.append(arguments)
        basetemp = Path(
            next(value for value in arguments if value.startswith("--basetemp=")).split(
                "=", 1
            )[1]
        )
        run_dir = basetemp.parent
        locked = basetemp / "locked"
        locked.mkdir(parents=True)
        (locked / "payload").write_text("test", encoding="utf-8")
        if os.name == "posix":
            locked.chmod(0o500)
        return 7

    result = run_pytest_module.run_pytest(
        ["tests/example.py", "-q"],
        environ=_environment(tmp_path),
        pytest_main=fake_pytest_main,
    )

    assert result == 7
    assert observed[0][0:2] == ["tests/example.py", "-q"]
    assert run_dir is not None
    assert not run_dir.exists()
    assert tuple(run_dir.parent.iterdir()) == ()


def test_managed_pytest_reclaims_only_valid_inactive_crash_residue(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    stale_scope = run_pytest_module.resolve_pytest_runtime_scope(
        environ=environment,
        run_id="a" * 32,
    )
    stale_scope.run_dir.mkdir(mode=0o700, parents=True)
    lease_path = stale_scope.run_dir / ".lease"
    lease_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": stale_scope.run_id,
                "pid": 1,
                "created_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    lease_path.chmod(0o600)
    (stale_scope.run_dir / "payload").write_bytes(b"residue")

    assert (
        run_pytest_module.run_pytest(
            [],
            environ=environment,
            pytest_main=lambda _arguments: 0,
        )
        == 0
    )

    assert not stale_scope.run_dir.exists()


def test_concurrent_managed_pytest_preserves_the_other_live_run(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    live_scope = run_pytest_module.resolve_pytest_runtime_scope(
        environ=environment,
        run_id="a" * 32,
    )
    live = RunLease.acquire(live_scope)
    observed_live: list[bool] = []

    def observe(_arguments: list[str]) -> int:
        observed_live.append(live_scope.run_dir.exists())
        return 0

    try:
        result = run_pytest_module.run_pytest(
            [],
            environ=environment,
            pytest_main=observe,
        )

        assert result == 0
        assert observed_live == [True]
        assert live_scope.run_dir.exists()
        assert live.active
    finally:
        live.close()


def test_managed_pytest_rejects_external_basetemp(tmp_path: Path) -> None:
    with pytest.raises(
        run_pytest_module.PytestScratchError,
        match="owned by",
    ):
        run_pytest_module.run_pytest(
            ["--basetemp=/tmp/caller-owned"],
            environ=_environment(tmp_path),
            pytest_main=lambda _arguments: 0,
        )

    assert not (tmp_path / "runtime").exists()


def test_managed_pytest_rejects_environment_basetemp(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["PYTEST_ADDOPTS"] = "-q --basetemp '/tmp/caller owned'"

    with pytest.raises(
        run_pytest_module.PytestScratchError,
        match="owned by",
    ):
        run_pytest_module.run_pytest(
            [],
            environ=environment,
            pytest_main=lambda _arguments: 0,
        )

    assert not (tmp_path / "runtime").exists()


def test_managed_pytest_rejects_invalid_capacity_configuration(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["LOUSHANG_PYTEST_MIN_FREE_BYTES"] = "invalid"

    with pytest.raises(
        run_pytest_module.PytestScratchError,
        match="non-negative integer",
    ):
        run_pytest_module.run_pytest(
            [],
            environ=environment,
            pytest_main=lambda _arguments: 0,
        )


def test_managed_pytest_refuses_insufficient_capacity_before_collection(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    environment["LOUSHANG_PYTEST_MIN_FREE_BYTES"] = str(1 << 80)
    called = False

    def observe(_arguments: list[str]) -> int:
        nonlocal called
        called = True
        return 0

    with pytest.raises(
        run_pytest_module.PytestScratchError,
        match="insufficient free capacity",
    ):
        run_pytest_module.run_pytest(
            [],
            environ=environment,
            pytest_main=observe,
        )

    assert called is False
    runs_root = tmp_path / "runtime" / "pytest-runs"
    assert not runs_root.exists() or tuple(runs_root.iterdir()) == ()


def test_make_pytest_targets_use_the_managed_runner() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "uv run pytest" not in makefile
    assert "run --extra dev pytest" not in makefile
    assert ".venv/bin/python -m pytest" not in makefile
    assert "PYTEST_RUNNER := python scripts/dev/run_pytest.py" in makefile
    assert makefile.count("$(PYTEST_RUNNER)") >= 10


def test_ci_pytest_jobs_use_the_managed_runner() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / ".github/workflows").glob("*.yml")
    )

    assert "uv run pytest" not in workflows


@pytest.mark.skipif(os.name != "posix", reason="POSIX private mode contract")
def test_managed_pytest_run_directory_is_private(tmp_path: Path) -> None:
    modes: list[int] = []

    def observe(arguments: list[str]) -> int:
        basetemp = Path(
            next(value for value in arguments if value.startswith("--basetemp=")).split(
                "=", 1
            )[1]
        )
        modes.append(stat.S_IMODE(basetemp.parent.stat().st_mode))
        return 0

    run_pytest_module.run_pytest(
        [],
        environ=_environment(tmp_path),
        pytest_main=observe,
    )

    assert modes == [0o700]
