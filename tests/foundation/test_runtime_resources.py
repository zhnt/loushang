from __future__ import annotations

import gc
from pathlib import Path

import pytest

from loushang.foundation.artifact_store import ArtifactStore
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_resources import RuntimeResourceOwner
from loushang.foundation.runtime_scope import resolve_runtime_scope


def _scope(tmp_path: Path, run_id: str = "a" * 32):
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
        temporary_root=tmp_path / "temporary",
    )
    return resolve_runtime_scope(paths=paths, run_id=run_id)


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
        snapshots = owner.artifact_snapshots
        artifact = snapshots.snapshot_file(
            source,
            logical_name="debug/latest.log",
            kind="debug-log",
            media_type="text/plain",
            disclosure="redact",
            allowed_roots=(source_root,),
        )

        assert snapshots.read_bytes(artifact) == b"debug"


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
    assert owner.artifact_writer is owner.artifact_reader
    assert owner.artifact_reader is owner.artifact_snapshots
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
