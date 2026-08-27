from __future__ import annotations

import gc
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import pytest

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
from loushang.harness.artifacts import ArtifactStore
from loushang.harness.runtime.resources import RuntimeResourceOwner


def _scope(tmp_path: Path, run_id: str = "a" * 32):
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
        temporary_root=tmp_path / "temporary",
    )
    return resolve_runtime_scope(paths=paths, run_id=run_id)


_CONCURRENT_ACQUIRE_SCRIPT = """
import sys
import time
from pathlib import Path

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import resolve_runtime_scope
from loushang.harness.runtime.resources import RuntimeResourceOwner

runtime_root = Path(sys.argv[1])
user_home = Path(sys.argv[2])
ready = Path(sys.argv[3])
start = Path(sys.argv[4])
release = Path(sys.argv[5])
result = Path(sys.argv[6])
paths = resolve_platform_paths(
    environ={"LOUSHANG_RUNTIME_DIR": str(runtime_root)},
    home=user_home,
    temporary_root=runtime_root.parent / "temporary",
)
scope = resolve_runtime_scope(paths=paths, run_id="f" * 32)
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 20
while not start.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("start signal was not published")
    time.sleep(0.01)
try:
    owner = RuntimeResourceOwner.acquire(scope)
except BaseException as error:
    result.write_text(f"error:{error.__class__.__name__}", encoding="utf-8")
else:
    result.write_text(f"acquired:{scope.run_id}", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("release signal was not published")
        time.sleep(0.01)
    owner.close()
"""


def _wait_for_paths(paths: tuple[Path, ...], *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not all(path.exists() for path in paths):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"process signals were not published: {paths!r}")
        time.sleep(0.01)


def test_runtime_resource_owner_composes_one_revocable_run_lifetime(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)

    with RuntimeResourceOwner.acquire(scope) as owner:
        writer = owner.artifact_writer
        reader = owner.artifact_reader
        artifact = writer.put_bytes(
            b"result",
            logical_name="outputs/result.txt",
            kind="output",
            media_type="text/plain",
        )

        assert owner.active is True
        assert owner.scope is scope
        assert owner.sweep_report.failed == 0
        assert reader.read_bytes(artifact) == b"result"
        assert (scope.run_dir / ".lease").is_file()

    assert owner.active is False
    assert not scope.run_dir.exists()
    with pytest.raises(RuntimeError, match="closed"):
        writer.put_bytes(
            b"late",
            logical_name="outputs/late.txt",
            kind="output",
            media_type="text/plain",
        )
    with pytest.raises(RuntimeError, match="closed"):
        reader.read_bytes(artifact)


def test_runtime_resource_owner_supplies_a_snapshot_only_port(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    source_root = tmp_path / "state" / "debug"
    source_root.mkdir(parents=True)
    source = source_root / "latest.log"
    source.write_bytes(b"debug")

    with RuntimeResourceOwner.acquire(scope) as owner:
        snapshots = owner.artifact_snapshots(allowed_roots=(source_root,))
        artifact = snapshots.snapshot_file(
            source,
            logical_name="debug/latest.log",
            kind="debug-log",
            media_type="text/plain",
            disclosure="redact",
        )

        assert snapshots.read_bytes(artifact) == b"debug"
        assert not hasattr(snapshots, "put_bytes")
        assert not hasattr(owner.artifact_writer, "read_bytes")
        assert not hasattr(owner.artifact_writer, "snapshot_file")
        assert not hasattr(owner.artifact_reader, "put_bytes")


def test_runtime_resource_owner_rolls_back_lease_when_service_build_fails(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)

    def fail_store(bound_scope):
        assert bound_scope is scope
        assert (scope.run_dir / ".lease").is_file()
        raise RuntimeError("store construction failed")

    with pytest.raises(RuntimeError, match="construction failed"):
        RuntimeResourceOwner.acquire(
            scope,
            artifact_store_factory=fail_store,
        )

    assert not scope.run_dir.exists()


def test_runtime_resource_owner_constructs_one_store_and_closes_idempotently(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    stores = []

    def build_store(bound_scope):
        store = ArtifactStore(bound_scope)
        stores.append(store)
        return store

    owner = RuntimeResourceOwner.acquire(
        scope,
        artifact_store_factory=build_store,
    )

    assert len(stores) == 1
    assert owner.artifact_writer is not owner.artifact_reader
    owner.close()
    owner.close()

    assert not scope.run_dir.exists()
    with pytest.raises(RuntimeError, match="closed"):
        _ = owner.sweep_report


def test_runtime_resource_owner_never_steals_an_active_scope(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    first = RuntimeResourceOwner.acquire(scope)

    with pytest.raises(FileExistsError):
        RuntimeResourceOwner.acquire(scope)

    assert first.active is True
    assert (scope.run_dir / ".lease").is_file()
    first.close()


def test_artifact_ports_do_not_extend_root_ownership(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    owner = RuntimeResourceOwner.acquire(scope)
    writer = owner.artifact_writer

    del owner
    gc.collect()

    assert not scope.run_dir.exists()
    with pytest.raises(RuntimeError, match="closed"):
        writer.put_bytes(
            b"late",
            logical_name="outputs/late.txt",
            kind="output",
            media_type="text/plain",
        )


def test_runtime_resource_owner_rejects_direct_construction(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    try:
        with pytest.raises(TypeError, match="created with acquire"):
            RuntimeResourceOwner(
                scope=scope,
                lease=lease,
                artifact_store=ArtifactStore(scope),
            )
    finally:
        lease.close()


def test_runtime_resource_owner_rejects_mismatched_store_scope(
    tmp_path: Path,
) -> None:
    target = _scope(tmp_path, "a" * 32)
    other = _scope(tmp_path, "b" * 32)
    other_lease = RunLease.acquire(other)
    try:
        with pytest.raises(ValueError, match="mismatched scope"):
            RuntimeResourceOwner.acquire(
                target,
                artifact_store_factory=lambda _scope: ArtifactStore(other),
            )
        assert not target.run_dir.exists()
        assert other_lease.active is True
        assert other.run_dir.exists()
    finally:
        other_lease.close()


@pytest.mark.parametrize("failure", (RuntimeError("failed"), KeyboardInterrupt()))
def test_runtime_resource_owner_rolls_back_partially_written_store(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    scope = _scope(tmp_path)

    def fail_after_write(bound_scope):
        store = ArtifactStore(bound_scope)
        store.put_bytes(
            b"partial",
            logical_name="outputs/partial.txt",
            kind="output",
            media_type="text/plain",
        )
        raise failure

    with pytest.raises(failure.__class__, match=str(failure) or None):
        RuntimeResourceOwner.acquire(
            scope,
            artifact_store_factory=fail_after_write,
        )

    assert not scope.run_dir.exists()


def test_runtime_resource_owner_context_preserves_body_failure(tmp_path: Path) -> None:
    scope = _scope(tmp_path)

    with pytest.raises(RuntimeError, match="body failed"):
        with RuntimeResourceOwner.acquire(scope):
            raise RuntimeError("body failed")

    assert not scope.run_dir.exists()


def test_runtime_resource_owner_close_drains_inflight_artifact_write(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    entered = Event()
    release = Event()
    outcomes = []
    failures = []

    class BlockingArtifactStore(ArtifactStore):
        def put_bytes(self, *args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test write was not released")
            return super().put_bytes(*args, **kwargs)

    owner = RuntimeResourceOwner.acquire(
        scope,
        artifact_store_factory=BlockingArtifactStore,
    )
    writer = owner.artifact_writer

    def write() -> None:
        try:
            outcomes.append(
                writer.put_bytes(
                    b"complete",
                    logical_name="outputs/complete.txt",
                    kind="output",
                    media_type="text/plain",
                )
            )
        except BaseException as error:
            failures.append(error)

    write_thread = Thread(target=write)
    close_thread = Thread(target=owner.close)
    write_thread.start()
    assert entered.wait(timeout=5)
    close_thread.start()
    deadline = time.monotonic() + 5
    while owner.active and time.monotonic() < deadline:
        time.sleep(0.001)
    assert owner.active is False
    assert close_thread.is_alive()
    assert scope.run_dir.exists()
    with pytest.raises(RuntimeError, match="closed"):
        writer.put_bytes(
            b"too late",
            logical_name="outputs/too-late.txt",
            kind="output",
            media_type="text/plain",
        )
    release.set()
    write_thread.join(timeout=5)
    close_thread.join(timeout=5)

    assert not write_thread.is_alive()
    assert not close_thread.is_alive()
    assert failures == []
    assert len(outcomes) == 1
    assert not scope.run_dir.exists()
    assert not (scope.run_dir / ".lease").exists()


def test_runtime_resource_owner_allows_only_one_cross_process_acquire(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    ready_paths = (tmp_path / "ready-1", tmp_path / "ready-2")
    result_paths = (tmp_path / "result-1", tmp_path / "result-2")
    start = tmp_path / "start"
    release = tmp_path / "release"
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CONCURRENT_ACQUIRE_SCRIPT,
                str(runtime_root),
                str(tmp_path / "home"),
                str(ready_path),
                str(start),
                str(release),
                str(result_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for ready_path, result_path in zip(ready_paths, result_paths, strict=True)
    ]
    try:
        _wait_for_paths(ready_paths, timeout=10)
        start.write_text("start", encoding="utf-8")
        _wait_for_paths(result_paths, timeout=10)
        outcomes = sorted(path.read_text(encoding="utf-8") for path in result_paths)
        assert [item.split(":", 1)[0] for item in outcomes] == [
            "acquired",
            "error",
        ]
        assert (runtime_root / "runs" / ("f" * 32) / ".lease").is_file()
    finally:
        release.write_text("release", encoding="utf-8")
        for process in processes:
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
    assert all(process.returncode == 0 for process in processes)
