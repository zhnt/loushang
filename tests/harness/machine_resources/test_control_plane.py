from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.machine_resources import (
    MachineResourceCleanRequest,
    clean_machine_resources,
    inspect_machine_resources,
    migrate_machine_resources,
    plan_machine_resource_migration,
    resolve_machine_resource_layout,
)
from loushang.harness.machine_resources import control_plane as control_plane_module
from loushang.harness.transcript import AGENT_MESSAGE_KIND, SessionImagePart
from loushang.harness.transcript.jsonl_file import write_agent_transcript_export
from loushang.harness.transcript.lifecycle import delete_agent_transcript_jsonl


def _paths(tmp_path: Path) -> PlatformPaths:
    home = tmp_path / "home" / ".loushang"
    return PlatformPaths(
        home=home,
        data=home / "data",
        state=home / "state",
        cache=home / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )


def _header(conversation_id: str) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )


def test_resource_layout_distinguishes_canonical_and_compatibility_paths(
    tmp_path: Path,
) -> None:
    layout = resolve_machine_resource_layout(
        platform_paths=_paths(tmp_path),
        cwd=tmp_path / "project",
    )

    by_id = {resource.resource_id: resource for resource in layout.resources}
    assert by_id["sessions.global"].path == _paths(tmp_path).data / "sessions"
    assert by_id["sessions.global"].mode == "canonical"
    assert by_id["sessions.cwd_compatibility"].path == (
        tmp_path / "project" / ".loushang" / "sessions"
    )
    assert by_id["sessions.cwd_compatibility"].mode == "compatibility"
    assert by_id["runtime.runs"].lifetime == "live_process"
    assert by_id["temporary.global"].cleanup.startswith("creating owner only")


def test_resource_status_is_bounded_and_does_not_follow_symlinks(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    sessions = paths.data / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "one.jsonl").write_bytes(b"one")
    (sessions / "two.jsonl").write_bytes(b"two")
    (sessions / "three.jsonl").write_bytes(b"three")
    try:
        (sessions / "outside-link").symlink_to(tmp_path)
    except OSError:
        if os.name == "nt":
            # Windows CI may not grant unprivileged symlink creation.
            pass
        else:
            raise
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)

    snapshot = inspect_machine_resources(layout, max_entries=2)

    session_status = next(
        status
        for status in snapshot.resources
        if status.resource.resource_id == "sessions.global"
    )
    assert 1 <= session_status.files <= 2
    assert 3 <= session_status.bytes <= 8
    assert session_status.directories == 1
    assert session_status.truncated is True
    assert session_status.state == "partial"


def test_resource_status_marks_a_linked_root_unsafe(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.data.mkdir(parents=True)
    try:
        (paths.data / "sessions").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            return
        raise
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)

    snapshot = inspect_machine_resources(layout)

    status = next(
        item
        for item in snapshot.resources
        if item.resource.resource_id == "sessions.global"
    )
    assert status.state == "unsafe"
    assert status.files == 0


def test_clean_preview_is_non_mutating_and_apply_removes_only_managed_archives(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    diagnostics = paths.state / "diagnostics"
    diagnostics.mkdir(parents=True)
    managed = diagnostics / "loushang-diag-2026.zip"
    unrelated = diagnostics / "keep.txt"
    managed.write_bytes(b"archive")
    unrelated.write_bytes(b"keep")
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)
    request = MachineResourceCleanRequest(targets=("diagnostics",))

    preview = clean_machine_resources(layout, request)

    assert preview.applied is False
    assert preview.reports[0].candidates == 1
    assert managed.exists()
    applied = clean_machine_resources(
        layout,
        MachineResourceCleanRequest(targets=("diagnostics",), apply=True),
    )
    assert applied.reports[0].removed == 1
    assert not managed.exists()
    assert unrelated.read_bytes() == b"keep"


def test_orphan_asset_cleanup_preserves_every_transcript_claimed_authority(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    sessions = paths.data / "sessions"
    sessions.mkdir(parents=True)
    write_agent_transcript_export(
        sessions / "live.jsonl",
        _header("live"),
        [],
    )
    live = SessionBlobStore(paths.data, "live")
    live.put_bytes(
        b"live",
        logical_name="images/live.png",
        kind="image",
        media_type="image/png",
    )
    orphan = SessionBlobStore(paths.data, "orphan")
    orphan.put_bytes(
        b"orphan",
        logical_name="images/orphan.png",
        kind="image",
        media_type="image/png",
    )
    orphan_transcript = sessions / "orphan.jsonl"
    write_agent_transcript_export(
        orphan_transcript,
        _header("orphan"),
        [],
    )
    assert asyncio.run(delete_agent_transcript_jsonl(orphan_transcript)) is True
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)

    result = clean_machine_resources(
        layout,
        MachineResourceCleanRequest(
            targets=("orphan_session_assets",),
            apply=True,
        ),
    )

    assert result.reports[0].removed == 1
    assert live.root.exists()
    assert not orphan.root.exists()


def test_orphan_asset_cleanup_fails_closed_on_corrupt_transcript(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    sessions = paths.data / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "corrupt.jsonl").write_text("not-json\n", encoding="utf-8")
    orphan = SessionBlobStore(paths.data, "orphan")
    orphan.put_bytes(
        b"orphan",
        logical_name="images/orphan.png",
        kind="image",
        media_type="image/png",
    )
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)

    result = clean_machine_resources(
        layout,
        MachineResourceCleanRequest(
            targets=("orphan_session_assets",),
            apply=True,
        ),
    )

    assert result.reports[0].failed == 1
    assert orphan.root.exists()


def test_orphan_asset_cleanup_rejects_linked_asset_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.data.mkdir(parents=True)
    try:
        (paths.data / "session-assets").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            return
        raise
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=tmp_path)

    result = clean_machine_resources(
        layout,
        MachineResourceCleanRequest(
            targets=("orphan_session_assets",),
            apply=True,
        ),
    )

    assert result.reports[0].failed == 1
    assert outside.exists()


@pytest.mark.parametrize("apply", [1, "false"])
def test_cleanup_apply_requires_an_exact_boolean(apply: object) -> None:
    with pytest.raises(TypeError, match="boolean"):
        MachineResourceCleanRequest(apply=apply)  # type: ignore[arg-type]


def test_compatibility_session_migration_copies_transcript_and_blobs_transactionally(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    project = tmp_path / "project"
    source_sessions = project / ".loushang" / "sessions"
    source_sessions.mkdir(parents=True)
    source_store = SessionBlobStore(project / ".loushang", "legacy-session")
    image = source_store.put_bytes(
        b"clipboard image",
        logical_name="images/clipboard.png",
        kind="image",
        media_type="image/png",
    )
    record = ConversationRecord(
        record_id="record-1",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-27T00:00:01Z",
        payload=UserMessage(
            role="user",
            content=[SessionImagePart(type="image", blob=image)],
            timestamp=1.0,
        ),
    )
    source = source_sessions / "legacy.jsonl"
    write_agent_transcript_export(source, _header("legacy-session"), [record])
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=project)

    plan = plan_machine_resource_migration(layout)
    results = asyncio.run(migrate_machine_resources(layout, plan))

    assert len(plan.candidates) == 1
    assert results[0].disposition == "migrated"
    assert source.exists()
    assert plan.candidates[0].destination.exists()
    target_store = SessionBlobStore(paths.data, "legacy-session")
    assert target_store.read_bytes(target_store.records[0]) == b"clipboard image"
    repeated = asyncio.run(migrate_machine_resources(layout, plan))
    assert repeated[0].disposition == "already_present"


def test_migration_fails_closed_when_source_changes_after_plan(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    project = tmp_path / "project"
    source_sessions = project / ".loushang" / "sessions"
    source_sessions.mkdir(parents=True)
    source = source_sessions / "legacy.jsonl"
    write_agent_transcript_export(source, _header("legacy-session"), [])
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=project)
    plan = plan_machine_resource_migration(layout)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    results = asyncio.run(migrate_machine_resources(layout, plan))

    assert results[0].disposition == "failed"
    assert "changed after planning" in (results[0].detail or "")
    assert not plan.candidates[0].destination.exists()


def test_migration_rejects_a_forged_destination_outside_canonical_root(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    source_sessions = tmp_path / "project" / ".loushang" / "sessions"
    source_sessions.mkdir(parents=True)
    source = source_sessions / "legacy.jsonl"
    write_agent_transcript_export(source, _header("legacy-session"), [])
    layout = resolve_machine_resource_layout(
        platform_paths=paths,
        cwd=tmp_path / "project",
    )
    plan = plan_machine_resource_migration(layout)
    outside = tmp_path / "outside.jsonl"
    forged = replace(plan.candidates[0], destination=outside)

    results = asyncio.run(
        migrate_machine_resources(layout, replace(plan, candidates=(forged,)))
    )

    assert results[0].disposition == "failed"
    assert "canonical authority" in (results[0].detail or "")
    assert not outside.exists()


def test_migration_preserves_blobs_when_create_outcome_is_unknown_but_committed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _paths(tmp_path)
    project = tmp_path / "project"
    source_sessions = project / ".loushang" / "sessions"
    source_sessions.mkdir(parents=True)
    source_store = SessionBlobStore(project / ".loushang", "legacy-session")
    image = source_store.put_bytes(
        b"clipboard image",
        logical_name="images/clipboard.png",
        kind="image",
        media_type="image/png",
    )
    record = ConversationRecord(
        record_id="record-1",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-27T00:00:01Z",
        payload=UserMessage(
            role="user",
            content=[SessionImagePart(type="image", blob=image)],  # type: ignore[list-item]
            timestamp=1.0,
        ),
    )
    source = source_sessions / "legacy.jsonl"
    write_agent_transcript_export(source, _header("legacy-session"), [record])
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=project)
    plan = plan_machine_resource_migration(layout)

    class _UnknownStore:
        async def create(self, _key, header, records, *, operation_id):
            del operation_id
            write_agent_transcript_export(
                plan.candidates[0].destination,
                header,
                list(records),
            )
            raise StoreCommitOutcomeUnknown("receipt was lost")

    monkeypatch.setattr(
        control_plane_module,
        "create_agent_transcript_file_store",
        lambda _layout: _UnknownStore(),
    )

    results = asyncio.run(migrate_machine_resources(layout, plan))

    assert results[0].disposition == "migrated"
    target_store = SessionBlobStore(paths.data, "legacy-session")
    assert target_store.read_bytes(target_store.records[0]) == b"clipboard image"


def test_migration_coordinates_cancellation_before_returning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        paths = _paths(tmp_path)
        project = tmp_path / "project"
        source_sessions = project / ".loushang" / "sessions"
        source_sessions.mkdir(parents=True)
        source = source_sessions / "legacy.jsonl"
        write_agent_transcript_export(source, _header("legacy-session"), [])
        layout = resolve_machine_resource_layout(platform_paths=paths, cwd=project)
        plan = plan_machine_resource_migration(layout)
        started = asyncio.Event()
        release = asyncio.Event()

        class _DelayedStore:
            async def create(self, _key, header, records, *, operation_id):
                del operation_id
                started.set()
                await release.wait()
                write_agent_transcript_export(
                    plan.candidates[0].destination,
                    header,
                    list(records),
                )

        monkeypatch.setattr(
            control_plane_module,
            "create_agent_transcript_file_store",
            lambda _layout: _DelayedStore(),
        )
        task = asyncio.create_task(migrate_machine_resources(layout, plan))
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert plan.candidates[0].destination.exists()

    asyncio.run(scenario())
