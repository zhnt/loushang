from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.harness.artifacts.store as artifact_store_module
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
from loushang.harness.artifacts import (
    ArtifactRetentionPolicy,
    ArtifactSourceRejected,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactStorePolicy,
    ArtifactStoreQuotaExceeded,
    sweep_managed_artifacts,
)


def _scope(tmp_path: Path, run_id: str = "a" * 32):
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
        temporary_root=tmp_path / "temporary",
    )
    return resolve_runtime_scope(paths=paths, run_id=run_id)


def test_artifact_store_writes_private_immutable_object_and_portable_manifest(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope, now=lambda: 123.0)

    artifact = store.put_bytes(
        b'{"event":"ready"}\n',
        logical_name="traces/latest.jsonl",
        kind="trace-jsonl",
        media_type="application/x-ndjson",
        disclosure="redact",
        source="observability.trace.latest",
    )

    assert store.records == (artifact,)
    assert not hasattr(artifact, "path")
    assert not hasattr(artifact, "_identity")
    assert store.total_bytes == len(b'{"event":"ready"}\n')
    assert store.read_bytes(artifact) == b'{"event":"ready"}\n'
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 1
    assert manifest["runId"] == scope.run_id
    assert manifest["artifacts"] == [artifact.manifest_entry()]
    assert str(scope.paths.runtime) not in json.dumps(manifest)
    with pytest.raises(ArtifactSourceRejected, match="not owned"):
        store.read_bytes(replace(artifact))
    if os.name == "posix":
        object_path = store.root / "objects" / artifact.artifact_id
        assert stat.S_IMODE(object_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700

    lease.close()

    assert not scope.run_dir.exists()


def test_artifact_store_requires_an_application_owned_live_run(tmp_path: Path) -> None:
    store = ArtifactStore(_scope(tmp_path))

    with pytest.raises(FileNotFoundError):
        store.put_bytes(
            b"content",
            logical_name="output.txt",
            kind="output",
            media_type="text/plain",
        )

    assert not store.scope.run_dir.exists()


def test_artifact_store_accepts_exact_limits_then_enforces_count(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(
        scope,
        policy=ArtifactStorePolicy(
            max_artifacts=1,
            max_artifact_bytes=4,
            max_total_bytes=4,
        ),
    )
    store.put_bytes(
        b"1234",
        logical_name="exact.bin",
        kind="output",
        media_type="application/octet-stream",
    )

    with pytest.raises(ArtifactStoreQuotaExceeded, match="count limit"):
        store.put_bytes(
            b"1",
            logical_name="extra.bin",
            kind="output",
            media_type="application/octet-stream",
        )

    assert len(store.records) == 1
    lease.close()


def test_artifact_store_enforces_per_artifact_and_total_byte_limits(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(
        scope,
        policy=ArtifactStorePolicy(
            max_artifacts=3,
            max_artifact_bytes=4,
            max_total_bytes=5,
        ),
    )

    with pytest.raises(ArtifactStoreQuotaExceeded, match="per-artifact"):
        store.put_bytes(
            b"large",
            logical_name="large.bin",
            kind="output",
            media_type="application/octet-stream",
        )
    store.put_bytes(
        b"123",
        logical_name="first.bin",
        kind="output",
        media_type="application/octet-stream",
    )
    with pytest.raises(ArtifactStoreQuotaExceeded, match="byte limit"):
        store.put_bytes(
            b"456",
            logical_name="second.bin",
            kind="output",
            media_type="application/octet-stream",
        )

    assert store.total_bytes == 3
    assert len(tuple((store.root / "objects").iterdir())) == 1
    lease.close()


@pytest.mark.parametrize(
    "logical_name",
    (
        "",
        "/absolute",
        "C:/windows-absolute",
        "../escape",
        "a/../escape",
        "a\\windows",
        "a//b",
    ),
)
def test_artifact_store_rejects_unsafe_logical_names(
    tmp_path: Path,
    logical_name: str,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)

    with pytest.raises(ValueError, match="safe relative path"):
        store.put_bytes(
            b"content",
            logical_name=logical_name,
            kind="output",
            media_type="text/plain",
        )

    assert not store.root.exists()
    lease.close()


def test_artifact_store_rolls_back_object_when_manifest_publication_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)

    def fail_manifest(_records) -> None:
        raise OSError("manifest unavailable")

    monkeypatch.setattr(store, "_write_manifest", fail_manifest)

    with pytest.raises(OSError, match="manifest unavailable"):
        store.put_bytes(
            b"content",
            logical_name="output.txt",
            kind="output",
            media_type="text/plain",
        )

    assert store.records == ()
    assert tuple((store.root / "objects").iterdir()) == ()
    lease.close()


def test_artifact_store_rejects_unknown_disclosure_before_disk_write(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)

    with pytest.raises(ValueError, match="unsupported artifact disclosure"):
        store.put_bytes(
            b"content",
            logical_name="output.txt",
            kind="output",
            media_type="text/plain",
            disclosure="public",  # type: ignore[arg-type]
        )

    assert not store.root.exists()
    lease.close()


def test_artifact_store_rejects_a_second_owner_for_the_same_run(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    first = ArtifactStore(scope)
    second = ArtifactStore(scope)
    first.put_bytes(
        b"first",
        logical_name="first.txt",
        kind="output",
        media_type="text/plain",
    )

    with pytest.raises(ArtifactStoreError, match="already initialized"):
        second.put_bytes(
            b"second",
            logical_name="second.txt",
            kind="output",
            media_type="text/plain",
        )

    assert [record.logical_name for record in first.records] == ["first.txt"]
    assert len(tuple((first.root / "objects").iterdir())) == 1
    lease.close()


def test_artifact_store_completes_short_os_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    write = os.write

    def short_write(descriptor: int, content: bytes) -> int:
        return write(descriptor, content[: max(1, len(content) // 3)])

    monkeypatch.setattr(artifact_store_module.os, "write", short_write)

    artifact = store.put_bytes(
        b"complete-content",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )

    assert store.read_bytes(artifact) == b"complete-content"
    lease.close()


def test_artifact_store_snapshots_only_regular_files_inside_allowed_roots(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    allowed = tmp_path / "state" / "debug"
    allowed.mkdir(parents=True)
    source = allowed / "debug.log"
    source.write_bytes(b"debug")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")

    artifact = store.snapshot_file(
        source,
        logical_name="debug/latest.log",
        kind="debug-log",
        media_type="text/plain",
        disclosure="redact",
        allowed_roots=(allowed,),
    )

    assert store.read_bytes(artifact) == b"debug"
    with pytest.raises(ArtifactSourceRejected, match="outside allowed roots"):
        store.snapshot_file(
            outside,
            logical_name="outside.txt",
            kind="output",
            media_type="text/plain",
            allowed_roots=(allowed,),
        )
    lease.close()


def test_artifact_store_requires_explicit_snapshot_roots(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    source = tmp_path / "debug.log"
    source.write_bytes(b"debug")

    with pytest.raises(ArtifactSourceRejected, match="explicit allowed root"):
        store.snapshot_file(
            source,
            logical_name="debug/latest.log",
            kind="debug-log",
            media_type="text/plain",
            allowed_roots=(),
        )

    assert not store.root.exists()
    lease.close()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_artifact_store_never_reads_a_symlink_outside_an_allowed_root(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    link = allowed / "latest"
    link.symlink_to(outside)

    with pytest.raises(ArtifactSourceRejected, match="outside allowed roots"):
        store.snapshot_file(
            link,
            logical_name="debug/latest.log",
            kind="debug-log",
            media_type="text/plain",
            allowed_roots=(allowed,),
        )

    assert not store.root.exists()
    lease.close()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_artifact_store_read_does_not_follow_a_replaced_object(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    artifact = store.put_bytes(
        b"safe",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    object_path = store.root / "objects" / artifact.artifact_id
    object_path.unlink()
    object_path.symlink_to(outside)

    with pytest.raises(ArtifactSourceRejected, match="identity changed"):
        store.read_bytes(artifact)

    assert outside.read_text(encoding="utf-8") == "secret"
    lease.close()


def test_managed_artifact_retention_applies_age_count_and_preserve(
    tmp_path: Path,
) -> None:
    root = tmp_path / "diagnostics"
    root.mkdir(mode=0o700)
    expired = root / "diag-expired.zip"
    oldest = root / "diag-oldest.zip"
    current = root / "diag-current.zip"
    unmanaged = root / "notes.txt"
    for path, content, modified_at in (
        (expired, b"expired", 1.0),
        (oldest, b"old", 90.0),
        (current, b"current", 100.0),
        (unmanaged, b"keep", 1.0),
    ):
        path.write_bytes(content)
        os.utime(path, (modified_at, modified_at))

    report = sweep_managed_artifacts(
        root,
        name_prefix="diag-",
        suffix=".zip",
        policy=ArtifactRetentionPolicy(
            max_files=1,
            max_total_bytes=1024,
            max_age_seconds=50,
        ),
        preserve=(current,),
        now=lambda: 100.0,
    )

    assert report.inspected == 3
    assert report.removed == 2
    assert not expired.exists()
    assert not oldest.exists()
    assert current.read_bytes() == b"current"
    assert unmanaged.read_bytes() == b"keep"


def test_managed_artifact_retention_applies_total_byte_budget(
    tmp_path: Path,
) -> None:
    root = tmp_path / "diagnostics"
    root.mkdir(mode=0o700)
    oldest = root / "diag-oldest.zip"
    newer = root / "diag-newer.zip"
    current = root / "diag-current.zip"
    for path, modified_at in ((oldest, 1.0), (newer, 2.0), (current, 3.0)):
        path.write_bytes(b"1234")
        os.utime(path, (modified_at, modified_at))

    report = sweep_managed_artifacts(
        root,
        name_prefix="diag-",
        suffix=".zip",
        policy=ArtifactRetentionPolicy(
            max_files=10,
            max_total_bytes=8,
            max_age_seconds=None,
        ),
        preserve=(current,),
    )

    assert report.removed == 1
    assert not oldest.exists()
    assert newer.exists()
    assert current.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_managed_artifact_retention_skips_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "diagnostics"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"keep")
    (root / "diag-link.zip").symlink_to(outside)

    report = sweep_managed_artifacts(
        root,
        name_prefix="diag-",
        suffix=".zip",
        policy=ArtifactRetentionPolicy(max_files=0, max_total_bytes=0),
    )

    assert report.skipped == 1
    assert outside.read_bytes() == b"keep"


def test_managed_artifact_retention_refuses_a_truncated_scan(tmp_path: Path) -> None:
    root = tmp_path / "diagnostics"
    root.mkdir(mode=0o700)
    first = root / "diag-first.zip"
    second = root / "diag-second.zip"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    report = sweep_managed_artifacts(
        root,
        name_prefix="diag-",
        suffix=".zip",
        policy=ArtifactRetentionPolicy(
            max_files=0,
            max_total_bytes=0,
            max_scan_entries=1,
        ),
    )

    assert report.truncated is True
    assert report.failed == 1
    assert first.exists()
    assert second.exists()


@pytest.mark.parametrize(("prefix", "suffix"), (("", ".zip"), ("diag-", "")))
def test_managed_artifact_retention_requires_a_narrow_name_family(
    tmp_path: Path,
    prefix: str,
    suffix: str,
) -> None:
    with pytest.raises(ValueError, match="prefix and suffix"):
        sweep_managed_artifacts(
            tmp_path,
            name_prefix=prefix,
            suffix=suffix,
        )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"max_artifacts": 0},
        {"max_artifact_bytes": 0},
        {"max_artifact_bytes": 2, "max_total_bytes": 1},
    ),
)
def test_artifact_store_policy_rejects_invalid_bounds(kwargs) -> None:
    with pytest.raises(ValueError):
        ArtifactStorePolicy(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"max_files": -1},
        {"max_total_bytes": -1},
        {"max_age_seconds": -1},
        {"max_scan_entries": 0},
    ),
)
def test_artifact_retention_policy_rejects_invalid_bounds(kwargs) -> None:
    with pytest.raises(ValueError):
        ArtifactRetentionPolicy(**kwargs)
