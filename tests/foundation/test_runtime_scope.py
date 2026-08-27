from __future__ import annotations

import gc
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import loushang.foundation.runtime_scope as runtime_scope_module
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import (
    RunLease,
    RuntimeScope,
    RuntimeSweepPolicy,
    resolve_runtime_scope,
    sweep_runtime_runs,
)


def _scope(tmp_path: Path, run_id: str):
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
        temporary_root=tmp_path / "temporary",
    )
    return resolve_runtime_scope(paths=paths, run_id=run_id)


def _inactive_run(
    tmp_path: Path,
    *,
    run_id: str,
    modified_at: float,
    leased: bool = True,
    payload: bytes = b"payload",
) -> Path:
    scope = _scope(tmp_path, run_id)
    scope.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    scope.run_dir.mkdir(mode=0o700)
    if leased:
        lease_path = scope.run_dir / ".lease"
        lease_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "pid": 1,
                    "created_at": modified_at,
                }
            ),
            encoding="utf-8",
        )
        lease_path.chmod(0o600)
        os.utime(lease_path, (modified_at, modified_at))
    payload_path = scope.run_dir / "payload"
    payload_path.write_bytes(payload)
    os.utime(payload_path, (modified_at, modified_at))
    os.utime(scope.run_dir, (modified_at, modified_at))
    return scope.run_dir


def test_runtime_scope_resolution_is_injectable_and_has_no_filesystem_effect(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path, "a" * 32)

    assert scope.run_dir == tmp_path / "runtime" / "runs" / ("a" * 32)
    assert scope.drafts == scope.run_dir / "drafts"
    assert not scope.paths.runtime.exists()


def test_sweep_is_a_noop_when_runtime_root_does_not_exist(tmp_path: Path) -> None:
    scope = _scope(tmp_path, "a" * 32)

    report = sweep_runtime_runs(scope)

    assert report.inspected == 0
    assert report.removed == 0
    assert not scope.paths.runtime.exists()


def test_run_lease_creates_private_tree_and_close_removes_it(tmp_path: Path) -> None:
    scope = _scope(tmp_path, "a" * 32)

    lease = RunLease.acquire(scope, now=lambda: 123.0)

    assert lease.active is True
    assert '"run_id":"' + ("a" * 32) + '"' in (scope.run_dir / ".lease").read_text(
        encoding="utf-8"
    )
    if os.name == "posix":
        assert stat.S_IMODE(scope.runs_root.stat().st_mode) == 0o700
        assert stat.S_IMODE(scope.run_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE((scope.run_dir / ".lease").stat().st_mode) == 0o600

    lease.close()
    lease.close()

    assert lease.active is False
    assert not scope.run_dir.exists()


def test_run_lease_completes_short_os_writes(tmp_path: Path, monkeypatch) -> None:
    scope = _scope(tmp_path, "a" * 32)
    write = os.write

    def short_write(descriptor: int, content: bytes) -> int:
        return write(descriptor, content[: max(1, len(content) // 3)])

    monkeypatch.setattr(runtime_scope_module.os, "write", short_write)

    lease = RunLease.acquire(scope, now=lambda: 123.0)

    record = json.loads((scope.run_dir / ".lease").read_text(encoding="utf-8"))
    assert record["run_id"] == scope.run_id
    lease.close()


def test_abandoned_run_lease_releases_its_descriptor_and_tree(tmp_path: Path) -> None:
    scope = _scope(tmp_path, "a" * 32)
    lease = RunLease.acquire(scope)
    assert scope.run_dir.exists()

    del lease
    gc.collect()

    assert not scope.run_dir.exists()


def test_sweep_preserves_a_live_locked_run_even_under_zero_limits(
    tmp_path: Path,
) -> None:
    live_scope = _scope(tmp_path, "a" * 32)
    sweep_scope = _scope(tmp_path, "b" * 32)
    live = RunLease.acquire(live_scope, now=lambda: 1.0)

    report = sweep_runtime_runs(
        sweep_scope,
        policy=RuntimeSweepPolicy(
            stale_after_seconds=0,
            max_inactive_runs=0,
            max_inactive_bytes=0,
        ),
        now=lambda: 10_000.0,
    )

    assert report.active == 1
    assert report.removed == 0
    assert live_scope.run_dir.exists()
    live.close()


def test_sweep_observes_a_real_child_process_lease_and_reclaims_its_crash(
    tmp_path: Path,
) -> None:
    run_id = "a" * 32
    runtime_dir = tmp_path / "runtime"
    child_source = "\n".join(
        (
            "import sys",
            "from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope",
            f"scope = resolve_runtime_scope(run_id={run_id!r})",
            "lease = RunLease.acquire(scope)",
            "print('ready', flush=True)",
            "sys.stdin.readline()",
        )
    )
    environ = dict(os.environ)
    environ["LOUSHANG_RUNTIME_DIR"] = str(runtime_dir)
    child = subprocess.Popen(
        [sys.executable, "-c", child_source],
        env=environ,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        live_scope = _scope(tmp_path, run_id)
        report = sweep_runtime_runs(
            _scope(tmp_path, "b" * 32),
            policy=RuntimeSweepPolicy(stale_after_seconds=0),
        )
        assert report.active == 1
        assert live_scope.run_dir.exists()

        child.kill()
        child.wait(timeout=10)

        report = sweep_runtime_runs(
            _scope(tmp_path, "c" * 32),
            policy=RuntimeSweepPolicy(stale_after_seconds=0),
        )
        assert report.removed == 1
        assert not live_scope.run_dir.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def test_sweep_removes_expired_leased_run_but_preserves_unprovable_legacy_run(
    tmp_path: Path,
) -> None:
    leased = _inactive_run(
        tmp_path,
        run_id="a" * 32,
        modified_at=10.0,
    )
    legacy = _inactive_run(
        tmp_path,
        run_id="b" * 32,
        modified_at=10.0,
        leased=False,
    )

    report = sweep_runtime_runs(
        _scope(tmp_path, "c" * 32),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=20,
            max_inactive_runs=32,
            max_inactive_bytes=1024,
        ),
        now=lambda: 100.0,
    )

    assert report.removed == 1
    assert not leased.exists()
    assert legacy.exists()


def test_sweep_quarantines_a_candidate_before_releasing_its_lease_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_id = "a" * 32
    run_dir = _inactive_run(tmp_path, run_id=run_id, modified_at=10.0)
    quarantine = runtime_scope_module._quarantine_run_tree
    observed_locked = False

    def observe_quarantine(*args, **kwargs):
        nonlocal observed_locked
        descriptor = runtime_scope_module._open_existing_private_file(
            run_dir / ".lease"
        )
        try:
            observed_locked = not runtime_scope_module._lock_descriptor(
                descriptor,
                blocking=False,
            )
        finally:
            runtime_scope_module._unlock_and_close(descriptor)
        return quarantine(*args, **kwargs)

    monkeypatch.setattr(
        runtime_scope_module,
        "_quarantine_run_tree",
        observe_quarantine,
    )

    report = sweep_runtime_runs(
        _scope(tmp_path, "b" * 32),
        policy=RuntimeSweepPolicy(stale_after_seconds=0),
        now=lambda: 100.0,
    )

    assert observed_locked is True
    assert report.removed == 1
    assert not run_dir.exists()


def test_sweep_releases_collected_candidate_locks_when_scanning_is_interrupted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _inactive_run(tmp_path, run_id="a" * 32, modified_at=10.0)
    _inactive_run(tmp_path, run_id="b" * 32, modified_at=20.0)
    inspect = runtime_scope_module._inspect_inactive_run
    inspected_paths: list[Path] = []

    def interrupt_second_inspection(*args, **kwargs):
        if inspected_paths:
            raise KeyboardInterrupt
        candidate = inspect(*args, **kwargs)
        assert candidate is not None
        inspected_paths.append(candidate.path)
        return candidate

    monkeypatch.setattr(
        runtime_scope_module,
        "_inspect_inactive_run",
        interrupt_second_inspection,
    )

    with pytest.raises(KeyboardInterrupt):
        sweep_runtime_runs(_scope(tmp_path, "c" * 32))

    descriptor = runtime_scope_module._open_existing_private_file(
        inspected_paths[0] / ".lease"
    )
    try:
        assert runtime_scope_module._lock_descriptor(
            descriptor,
            blocking=False,
        )
    finally:
        runtime_scope_module._unlock_and_close(descriptor)


def test_sweep_reclaims_an_interrupted_quarantine_entry(tmp_path: Path) -> None:
    run_id = "a" * 32
    run_dir = _inactive_run(tmp_path, run_id=run_id, modified_at=10.0)
    quarantined = run_dir.with_name(f".gc-{run_id}-{'d' * 32}")
    run_dir.rename(quarantined)

    report = sweep_runtime_runs(
        _scope(tmp_path, "b" * 32),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=10_000,
            max_inactive_runs=32,
            max_inactive_bytes=1024,
        ),
        now=lambda: 100.0,
    )

    assert report.removed == 1
    assert not quarantined.exists()


def test_sweep_uses_quota_only_for_runs_with_provably_inactive_leases(
    tmp_path: Path,
) -> None:
    oldest = _inactive_run(
        tmp_path,
        run_id="a" * 32,
        modified_at=10.0,
    )
    retained = _inactive_run(
        tmp_path,
        run_id="b" * 32,
        modified_at=20.0,
    )
    legacy = _inactive_run(
        tmp_path,
        run_id="c" * 32,
        modified_at=5.0,
        leased=False,
    )

    report = sweep_runtime_runs(
        _scope(tmp_path, "d" * 32),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=10_000,
            max_inactive_runs=1,
            max_inactive_bytes=1024,
        ),
        now=lambda: 100.0,
    )

    assert report.removed == 1
    assert not oldest.exists()
    assert retained.exists()
    assert legacy.exists()


def test_sweep_preserves_a_corrupt_unlocked_lease(tmp_path: Path) -> None:
    corrupt = _inactive_run(
        tmp_path,
        run_id="a" * 32,
        modified_at=10.0,
    )
    (corrupt / ".lease").write_text("{}", encoding="utf-8")
    os.utime(corrupt / ".lease", (10.0, 10.0))

    report = sweep_runtime_runs(
        _scope(tmp_path, "b" * 32),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=10_000,
            max_inactive_runs=0,
            max_inactive_bytes=0,
        ),
        now=lambda: 100.0,
    )

    assert report.removed == 0
    assert corrupt.exists()


def test_sweep_refuses_a_truncated_runtime_scan(tmp_path: Path) -> None:
    first = _inactive_run(tmp_path, run_id="a" * 32, modified_at=1.0)
    second = _inactive_run(tmp_path, run_id="b" * 32, modified_at=1.0)

    report = sweep_runtime_runs(
        _scope(tmp_path, "c" * 32),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=0,
            max_inactive_runs=0,
            max_inactive_bytes=0,
            max_scan_entries=1,
        ),
        now=lambda: 100.0,
    )

    assert report.truncated is True
    assert report.failed == 1
    assert first.exists()
    assert second.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_run_lease_rejects_a_symlinked_runs_root(tmp_path: Path) -> None:
    scope = _scope(tmp_path, "a" * 32)
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    scope.paths.runtime.mkdir(parents=True)
    scope.runs_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(NotADirectoryError):
        RunLease.acquire(scope)

    assert tuple(outside.iterdir()) == ()


@pytest.mark.skipif(os.name != "posix", reason="ownership semantics are POSIX-specific")
def test_sweep_rejects_runs_root_not_owned_by_current_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scope = _scope(tmp_path, "a" * 32)
    scope.runs_root.mkdir(mode=0o700, parents=True)
    actual_uid = scope.runs_root.stat().st_uid
    monkeypatch.setattr(os, "getuid", lambda: actual_uid + 1)

    with pytest.raises(PermissionError, match="not owned"):
        sweep_runtime_runs(scope)


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_sweep_never_follows_or_removes_unrecognized_symlinks(tmp_path: Path) -> None:
    scope = _scope(tmp_path, "b" * 32)
    scope.runs_root.mkdir(mode=0o700, parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("safe", encoding="utf-8")
    (scope.runs_root / ("a" * 32)).symlink_to(outside, target_is_directory=True)

    report = sweep_runtime_runs(
        scope,
        policy=RuntimeSweepPolicy(stale_after_seconds=0),
        now=lambda: 100.0,
    )

    assert report.skipped == 1
    assert marker.read_text(encoding="utf-8") == "safe"


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_sweep_unlinks_nested_symlink_without_touching_target(tmp_path: Path) -> None:
    run_dir = _inactive_run(
        tmp_path,
        run_id="a" * 32,
        modified_at=10.0,
    )
    outside = tmp_path / "outside-nested"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("safe", encoding="utf-8")
    link = run_dir / "link"
    link.symlink_to(outside, target_is_directory=True)
    os.utime(link, (10.0, 10.0), follow_symlinks=False)
    os.utime(run_dir, (10.0, 10.0))

    report = sweep_runtime_runs(
        _scope(tmp_path, "b" * 32),
        policy=RuntimeSweepPolicy(stale_after_seconds=20),
        now=lambda: 100.0,
    )

    assert report.removed == 1
    assert marker.read_text(encoding="utf-8") == "safe"


@pytest.mark.parametrize("run_id", ("short", "g" * 32, "A" * 31))
def test_runtime_scope_rejects_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )

    with pytest.raises(ValueError, match="runtime run id"):
        resolve_runtime_scope(paths=paths, run_id=run_id)

    with pytest.raises(ValueError, match="runtime run id"):
        RuntimeScope(paths=paths, run_id=run_id)
