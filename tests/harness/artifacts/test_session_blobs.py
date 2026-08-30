from __future__ import annotations

import json
from pathlib import Path

import pytest

import loushang.harness.artifacts.session_blobs as session_blobs_module
from loushang.harness.artifacts import (
    ArtifactSourceRejected,
    ArtifactStoreQuotaExceeded,
    SessionBlobManifestError,
    SessionBlobPolicy,
    SessionBlobStore,
    session_blob_authority_id,
)


def test_legacy_conversation_id_maps_to_stable_portable_blob_authority(
    tmp_path: Path,
) -> None:
    first = SessionBlobStore(tmp_path / "data", "legacy session")
    second = SessionBlobStore(tmp_path / "data", "legacy session")

    assert first.session_id == second.session_id
    assert first.session_id == session_blob_authority_id("legacy session")
    assert first.session_id.startswith("legacy-")
    assert SessionBlobStore(tmp_path / "data", "portable-id").session_id == "portable-id"


def test_session_blob_store_persists_and_resumes_portably(tmp_path: Path) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1", now=lambda: 2.0)
    reference = store.put_bytes(
        b"hello",
        logical_name="commands/stdout.txt",
        kind="command-output",
        media_type="text/plain",
        source="run-artifact:source-1",
    )

    resumed = SessionBlobStore(tmp_path / "data", "session-1")

    assert resumed.records == (reference,)
    assert resumed.read_bytes(reference) == b"hello"
    manifest = json.loads(resumed.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sessionId"] == "session-1"
    assert "path" not in json.dumps(manifest).lower()
    assert resumed.objects_root.joinpath(reference.blob_id).read_bytes() == b"hello"


def test_session_blob_store_deduplicates_content_objects(tmp_path: Path) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1")

    first = store.put_bytes(
        b"same",
        logical_name="one.txt",
        kind="output",
        media_type="text/plain",
    )
    second = store.put_bytes(
        b"same",
        logical_name="two.txt",
        kind="output",
        media_type="text/plain",
    )

    assert first.blob_id == second.blob_id
    assert len(tuple(store.objects_root.iterdir())) == 1
    assert len(store.records) == 2
    assert store.total_bytes == 4


def test_session_blob_store_reports_missing_blob_without_failing_resume(
    tmp_path: Path,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1")
    reference = store.put_bytes(
        b"content",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )
    store.objects_root.joinpath(reference.blob_id).unlink()

    resumed = SessionBlobStore(tmp_path / "data", "session-1")
    health = resumed.inspect()

    assert len(health) == 1
    assert health[0].state == "missing"
    with pytest.raises(FileNotFoundError):
        resumed.read_bytes(reference)


def test_session_blob_store_rejects_corrupt_blob(tmp_path: Path) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1")
    reference = store.put_bytes(
        b"content",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )
    store.objects_root.joinpath(reference.blob_id).write_bytes(b"changed")

    assert store.inspect()[0].state == "corrupt"
    with pytest.raises(ArtifactSourceRejected):
        store.read_bytes(reference)


def test_session_blob_store_clones_selected_refs_and_rebinds_session_id(
    tmp_path: Path,
) -> None:
    source = SessionBlobStore(tmp_path / "data", "source")
    selected = source.put_bytes(
        b"selected",
        logical_name="selected.txt",
        kind="output",
        media_type="text/plain",
    )
    source.put_bytes(
        b"not-selected",
        logical_name="other.txt",
        kind="output",
        media_type="text/plain",
    )
    target = SessionBlobStore(tmp_path / "data", "target")

    cloned = source.clone_into(target, [selected])

    assert len(cloned) == 1
    assert cloned[0].session_id == "target"
    assert cloned[0].sha256 == selected.sha256
    assert target.read_bytes(cloned[0]) == b"selected"
    assert len(target.records) == 1


def test_session_blob_store_enforces_count_and_byte_quotas(tmp_path: Path) -> None:
    store = SessionBlobStore(
        tmp_path / "data",
        "session-1",
        policy=SessionBlobPolicy(
            max_blobs=1,
            max_blob_bytes=4,
            max_total_bytes=4,
        ),
    )
    store.put_bytes(
        b"1234",
        logical_name="one",
        kind="output",
        media_type="text/plain",
    )

    with pytest.raises(ArtifactStoreQuotaExceeded):
        store.put_bytes(
            b"x",
            logical_name="two",
            kind="output",
            media_type="text/plain",
        )


def test_session_blob_store_rejects_manifest_identity_mismatch(tmp_path: Path) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1")
    store.put_bytes(
        b"content",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    manifest["sessionId"] = "another-session"
    store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SessionBlobManifestError, match="identity"):
        SessionBlobStore(tmp_path / "data", "session-1")


def test_session_blob_store_delete_removes_only_its_session_root(tmp_path: Path) -> None:
    first = SessionBlobStore(tmp_path / "data", "first")
    first.put_bytes(
        b"first",
        logical_name="first.txt",
        kind="output",
        media_type="text/plain",
    )
    second = SessionBlobStore(tmp_path / "data", "second")
    second.put_bytes(
        b"second",
        logical_name="second.txt",
        kind="output",
        media_type="text/plain",
    )

    assert first.delete() is True

    assert not first.root.exists()
    assert second.root.exists()
    assert second.delete() is True
    assert second.delete() is False


def test_session_blob_store_reloads_manifest_under_cross_instance_lock(
    tmp_path: Path,
) -> None:
    first = SessionBlobStore(tmp_path / "data", "session-1")
    stale_second = SessionBlobStore(tmp_path / "data", "session-1")

    first.put_bytes(
        b"first",
        logical_name="first.txt",
        kind="output",
        media_type="text/plain",
    )
    stale_second.put_bytes(
        b"second",
        logical_name="second.txt",
        kind="output",
        media_type="text/plain",
    )

    resumed = SessionBlobStore(tmp_path / "data", "session-1")
    assert [reference.logical_name for reference in resumed.records] == [
        "first.txt",
        "second.txt",
    ]


def test_publication_rollback_never_deletes_concurrent_changes(tmp_path: Path) -> None:
    source = SessionBlobStore(tmp_path / "source", "source")
    source_ref = source.put_bytes(
        b"source",
        logical_name="source.txt",
        kind="output",
        media_type="text/plain",
    )
    target = SessionBlobStore(tmp_path / "data", "target")
    publication = target.import_blobs(
        ((source_ref, b"source"),),
        require_new_authority=True,
    )
    concurrent = SessionBlobStore(tmp_path / "data", "target")
    concurrent.put_bytes(
        b"concurrent",
        logical_name="concurrent.txt",
        kind="output",
        media_type="text/plain",
    )

    assert publication.rollback() is False
    resumed = SessionBlobStore(tmp_path / "data", "target")
    assert {reference.logical_name for reference in resumed.records} == {
        "source.txt",
        "concurrent.txt",
    }


def test_publication_rollback_preserves_older_session_blobs(tmp_path: Path) -> None:
    store = SessionBlobStore(tmp_path / "data", "session-1")
    older = store.put_bytes(
        b"older",
        logical_name="older.txt",
        kind="output",
        media_type="text/plain",
    )
    source = SessionBlobStore(tmp_path / "source", "source")
    incoming = source.put_bytes(
        b"incoming",
        logical_name="incoming.txt",
        kind="output",
        media_type="text/plain",
    )
    publication = store.import_blobs(((incoming, b"incoming"),))

    assert publication.rollback() is True

    resumed = SessionBlobStore(tmp_path / "data", "session-1")
    assert resumed.records == (older,)
    assert resumed.read_bytes(older) == b"older"
    assert not resumed.objects_root.joinpath(incoming.blob_id).exists()


def test_new_object_directory_is_synced_before_manifest_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced: list[Path] = []
    original = session_blobs_module._sync_directory

    def recording_sync(path: Path) -> None:
        synced.append(path)
        original(path)

    monkeypatch.setattr(session_blobs_module, "_sync_directory", recording_sync)
    store = SessionBlobStore(tmp_path / "data", "session-1")
    store.put_bytes(
        b"content",
        logical_name="output.txt",
        kind="output",
        media_type="text/plain",
    )

    assert store.objects_root in synced
    assert store.root in synced
    assert synced.index(store.objects_root) < synced.index(store.root)
