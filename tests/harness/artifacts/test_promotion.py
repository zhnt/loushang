from __future__ import annotations

from pathlib import Path

import pytest

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
from loushang.harness.artifacts import (
    ArtifactPromotionError,
    ArtifactPromotionService,
    ArtifactStore,
    SessionBlobStore,
)


@pytest.fixture
def run_store(tmp_path: Path):
    paths = resolve_platform_paths(
        environ={"LOUSHANG_HOME": str(tmp_path / "home")},
        temporary_root=tmp_path / "tmp",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="a" * 32)
    lease = RunLease.acquire(scope)
    try:
        yield ArtifactStore(scope)
    finally:
        lease.close()


def test_promotion_to_session_rereads_verified_run_bytes(
    tmp_path: Path,
    run_store: ArtifactStore,
) -> None:
    artifact = run_store.put_bytes(
        b"complete output",
        logical_name="command/stdout.txt",
        kind="command-output",
        media_type="text/plain",
        disclosure="private",
    )
    session_store = SessionBlobStore(tmp_path / "data", "session-1")

    blob = ArtifactPromotionService(
        run_store,
        session_writer=session_store,
        now=lambda: 3.0,
    ).promote_to_session(artifact)

    assert session_store.read_bytes(blob) == b"complete output"
    assert blob.session_id == "session-1"
    assert blob.sha256 == artifact.sha256
    assert blob.source == f"run-artifact:{artifact.artifact_id}"


def test_explicit_user_export_is_atomic_non_overwriting_and_pathless(
    tmp_path: Path,
    run_store: ArtifactStore,
) -> None:
    artifact = run_store.put_bytes(
        b"public",
        logical_name="report.txt",
        kind="report",
        media_type="text/plain",
        disclosure="shareable",
    )
    destination = tmp_path / "exports" / "report.txt"
    service = ArtifactPromotionService(run_store, now=lambda: 4.0)

    result = service.export_to_user(artifact, destination)

    assert result.path == destination.resolve()
    assert destination.read_bytes() == b"public"
    assert "path" not in result.reference.manifest_entry()
    assert tuple(destination.parent.glob(".*.tmp")) == ()
    with pytest.raises(FileExistsError):
        service.export_to_user(artifact, destination)
    assert destination.read_bytes() == b"public"


def test_private_export_requires_separate_explicit_consent(
    tmp_path: Path,
    run_store: ArtifactStore,
) -> None:
    artifact = run_store.put_bytes(
        b"secret",
        logical_name="secret.txt",
        kind="output",
        media_type="text/plain",
        disclosure="private",
    )
    service = ArtifactPromotionService(run_store)

    with pytest.raises(ArtifactPromotionError, match="allow_private"):
        service.export_to_user(artifact, tmp_path / "secret.txt")

    result = service.export_to_user(
        artifact,
        tmp_path / "secret.txt",
        allow_private=True,
    )
    assert result.path.read_bytes() == b"secret"


def test_redact_export_requires_and_applies_transform(
    tmp_path: Path,
    run_store: ArtifactStore,
) -> None:
    artifact = run_store.put_bytes(
        b"token=secret",
        logical_name="diagnostic.txt",
        kind="diagnostic",
        media_type="text/plain",
        disclosure="redact",
    )
    service = ArtifactPromotionService(run_store)

    with pytest.raises(ArtifactPromotionError, match="redactor"):
        service.export_to_user(artifact, tmp_path / "diagnostic.txt")

    result = service.export_to_user(
        artifact,
        tmp_path / "diagnostic.txt",
        redactor=lambda value: value.replace(b"secret", b"[redacted]"),
    )
    assert result.path.read_bytes() == b"token=[redacted]"
    assert result.reference.sha256 != artifact.sha256
    assert result.reference.disclosure == "shareable"
