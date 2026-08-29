from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import TextPart, UserMessage
from loushang.coding.bootstrap import create_agent_session_runtime
from loushang.coding.continuity import (
    ConflictedContinuityTargetError,
    StaleContinuityTargetError,
    bind_coding_continuity,
    shutdown_coding_continuity,
)
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.continuity import ContinuityQuery
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptDirectoryRuntime,
    SessionImagePart,
    write_agent_transcript_export,
)
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.attachments import stage_clipboard_image
from loushang.tui.clipboard_image import ClipboardImage


def _header(
    conversation_id: str,
    *,
    cwd: str = "/workspace/project",
) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-24T00:00:00Z",
        metadata={"cwd": cwd},
    )


def _record(record_id: str, text: str, *, parent_id: str | None = None):
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-24T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=1.0),
    )


def _image_model() -> Model:
    return Model(
        id="image-model",
        name="Image model",
        provider="test",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            input=("text", "image"),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


class _Runtime(AgentTranscriptDirectoryRuntime):
    def __init__(self, session_dir: Path) -> None:
        super().__init__(
            session_dir=session_dir,
            session_index_flush_delay=60.0,
        )
        self.prepared: list[str] = []
        self.restored: list[str] = []
        self.deleted: list[str] = []
        self.aborted: list[str] = []
        self.current_session: object | None = None
        self.current_session_ref: str | None = None
        self.on_prepare: Callable[[], None] | None = None

    def get_current_session(self) -> object | None:
        return self.current_session

    def get_current_session_ref(self) -> str | None:
        return self.current_session_ref

    def _resolve_reference(self, session_id: str | Path) -> Path:
        candidate = Path(session_id).expanduser()
        if candidate.exists():
            return candidate.resolve()
        matches = [
            summary
            for summary in self.list_discovered_session_summaries(
                session_id_prefix=str(session_id)
            )
            if summary.session_id == str(session_id)
        ]
        if len(matches) != 1 or matches[0].session_file is None:
            raise ValueError("Session identity is not uniquely resolvable")
        discovery = matches[0].discovery
        if discovery is not None and not discovery.resumable:
            raise ConflictedContinuityTargetError("Session identity is conflicted")
        return matches[0].session_file

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        **_kwargs: object,
    ) -> object:
        reference = str(self._resolve_reference(session_id))
        self.prepared.append(reference)
        if self.on_prepare is not None:
            self.on_prepare()
        runtime = self

        class _Candidate:
            async def consume(self) -> object:
                runtime.restored.append(reference)
                return {"current": reference}

            async def abort(self) -> None:
                runtime.aborted.append(reference)

        return _Candidate()

    async def delete_session(self, session_id: str | Path) -> bool:
        reference = str(self._resolve_reference(session_id))
        self.deleted.append(reference)
        Path(reference).unlink()
        return True


def test_coding_provider_projects_common_summary_preview_and_activation(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Explain the parser architecture")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)
    assert bind_coding_continuity(runtime) is composition

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        summary = page.items[0]
        assert summary.title == "Explain the parser architecture"
        assert summary.subtitle == "/workspace/project"
        assert summary.domain_ids == ("coding",)
        assert summary.target.opaque_id == "session-1"
        assert not hasattr(summary, "branch")
        assert not hasattr(summary, "worktree")
        assert not hasattr(summary, "model")

        preview = await composition.hub.preview(summary.target)
        assert preview.heading == summary.title
        assert preview.sections[1].kind == "key_value"
        assert ("Messages", "1") in preview.sections[1].rows
        assert ("Storage", "Custom canonical") in preview.sections[1].rows
        assert ("Assets", "None") in preview.sections[1].rows

        lease = await composition.hub.prepare(summary.target)
        assert runtime.prepared == [str(transcript)]
        assert runtime.restored == []
        await lease.consume()
        assert runtime.restored == [str(transcript)]
        await composition.dispose()
        assert bind_coding_continuity(runtime) is composition
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_resume_discovery_defaults_to_current_cwd(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "current.jsonl",
        _header("current", cwd="/workspace/current"),
        [_record("current-record", "Resume current workspace")],
    )
    write_agent_transcript_export(
        tmp_path / "other.jsonl",
        _header("other", cwd="/workspace/other"),
        [_record("other-record", "Resume other workspace")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime, cwd="/workspace/current")

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert [item.target.opaque_id for item in page.items] == ["current"]
        assert page.items[0].subtitle == "/workspace/current"
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_resume_discovery_can_list_user_global_sessions(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "current.jsonl",
        _header("current", cwd="/workspace/current"),
        [_record("current-record", "Resume current workspace")],
    )
    write_agent_transcript_export(
        tmp_path / "other.jsonl",
        _header("other", cwd="/workspace/other"),
        [_record("other-record", "Resume other workspace")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(
        runtime,
        cwd="/workspace/current",
        all_sessions=True,
    )

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert {item.target.opaque_id for item in page.items} == {
            "current",
            "other",
        }
        assert {item.subtitle for item in page.items} == {
            "/workspace/current",
            "/workspace/other",
        }
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_resume_discovery_includes_legacy_current_cwd_sessions(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "user-home" / "data" / "sessions"
    legacy_dir = tmp_path / "project" / ".loushang" / "sessions"
    global_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    runtime = _Runtime(global_dir)
    runtime.add_session_discovery_dir(legacy_dir)
    write_agent_transcript_export(
        legacy_dir / "legacy.jsonl",
        _header("legacy", cwd="/workspace/current"),
        [_record("legacy-record", "Resume legacy workspace session")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime, cwd="/workspace/current")

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert [item.target.opaque_id for item in page.items] == ["legacy"]
        assert page.items[0].subtitle == (
            "/workspace/current · Configured compatibility"
        )
        assert page.items[0].status == "Legacy · configured"
        preview = await composition.hub.preview(page.items[0].target)
        assert ("Storage", "Configured compatibility") in preview.sections[1].rows
        assert ("Assets", "None") in preview.sections[1].rows
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_resume_refuses_conflicting_discovery_authorities(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "home" / "data" / "sessions"
    cwd_legacy_dir = tmp_path / "project" / ".loushang" / "sessions"
    home_legacy_dir = tmp_path / "home" / ".loushang" / "sessions"
    global_dir.mkdir(parents=True)
    cwd_legacy_dir.mkdir(parents=True)
    home_legacy_dir.mkdir(parents=True)
    write_agent_transcript_export(
        cwd_legacy_dir / "cwd.jsonl",
        _header("duplicate"),
        [_record("cwd-record", "Cwd legacy content")],
    )
    write_agent_transcript_export(
        home_legacy_dir / "home.jsonl",
        _header("duplicate"),
        [_record("home-record", "Different home legacy content")],
    )
    runtime = _Runtime(global_dir)
    runtime.add_session_discovery_dir(cwd_legacy_dir)
    runtime.add_session_discovery_dir(home_legacy_dir)
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        assert page.items[0].status == "Conflict"
        preview = await composition.hub.preview(page.items[0].target)
        assert ("Conflicting copies", "1") in preview.sections[1].rows
        with pytest.raises(ConflictedContinuityTargetError, match="different"):
            await composition.hub.prepare(page.items[0].target)
        assert runtime.prepared == []
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_resume_preview_inspects_durable_clipboard_image_health(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "data" / "sessions"
    session_dir.mkdir(parents=True)
    store = SessionBlobStore(tmp_path / "data", "image-session")
    image = store.put_bytes(
        b"clipboard image",
        logical_name="images/clipboard.png",
        kind="image",
        media_type="image/png",
    )
    write_agent_transcript_export(
        session_dir / "image-session.jsonl",
        _header("image-session"),
        [
            ConversationRecord(
                record_id="image-record",
                parent_id=None,
                kind=AGENT_MESSAGE_KIND,
                payload_version=1,
                created_at="2026-07-24T00:00:01Z",
                payload=UserMessage(
                    role="user",
                    content=[SessionImagePart(type="image", blob=image)],  # type: ignore[list-item]
                    timestamp=1.0,
                ),
            )
        ],
    )
    runtime = _Runtime(session_dir)
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        preview = await composition.hub.preview(page.items[0].target)
        assert (
            "Assets",
            "Present (integrity checked on resume) · 1 objects · 15 bytes",
        ) in preview.sections[1].rows
        (store.objects_root / image.blob_id).unlink()
        degraded = await composition.hub.preview(page.items[0].target)
        assert (
            "Assets",
            "Missing · 1 objects · 15 bytes · 1 missing · 0 corrupt",
        ) in degraded.sections[1].rows
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_continuity_builds_a_bounded_fallback_when_index_is_missing(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "fallback.jsonl",
        _header("fallback"),
        [_record("fallback-record", "Resume without an index")],
    )
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert [item.target.opaque_id for item in page.items] == ["fallback"]
        assert page.aggregate_index_state == "rebuilding"
        assert [item.code for item in page.provider_diagnostics] == [
            "coding_continuity_bounded_catalog"
        ]
        assert not runtime.session_catalog.index_path.exists()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_continuity_projects_delete_only_for_canonical_targets(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    compatibility = tmp_path / "compatibility"
    canonical.mkdir()
    compatibility.mkdir()
    write_agent_transcript_export(
        canonical / "canonical.jsonl",
        _header("canonical"),
        [_record("canonical-record", "Canonical")],
    )
    write_agent_transcript_export(
        compatibility / "legacy.jsonl",
        _header("legacy"),
        [_record("legacy-record", "Legacy")],
    )
    runtime = _Runtime(canonical)
    runtime.add_session_discovery_dir(compatibility)
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        actions = {item.target.opaque_id: item.actions for item in page.items}
        assert actions == {
            "canonical": ("activate", "delete"),
            "legacy": ("activate",),
        }
        legacy = next(item for item in page.items if item.target.opaque_id == "legacy")
        with pytest.raises(RuntimeError, match="read-only"):
            await composition.hub.delete(legacy.target)
        assert runtime.deleted == []
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_delete_action_filters_before_provider_pagination(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    compatibility = tmp_path / "compatibility"
    canonical.mkdir()
    compatibility.mkdir()
    write_agent_transcript_export(
        canonical / "canonical.jsonl",
        _header("canonical"),
        [_record("canonical-record", "Canonical")],
    )
    for index in range(40):
        write_agent_transcript_export(
            compatibility / f"legacy-{index}.jsonl",
            _header(f"legacy-{index}"),
            [_record(f"legacy-record-{index}", "Legacy")],
        )
    runtime = _Runtime(canonical)
    runtime.add_session_discovery_dir(compatibility)
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(
            ContinuityQuery(
                page_size=1,
                required_actions=("delete",),
            )
        )
        assert [item.target.opaque_id for item in page.items] == ["canonical"]
        assert page.next_cursor is None
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_clipboard_image_persists_through_transcript_and_continuity_preview(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "data" / "sessions"
    project = tmp_path / "project"
    session_dir.mkdir(parents=True)
    project.mkdir()
    clipboard_bytes = b"real clipboard png payload"
    outcome = stage_clipboard_image(
        lambda: ClipboardImage(bytes=clipboard_bytes, mime_type="image/png"),
        directory=tmp_path / "runtime" / "drafts" / "clipboard",
        display_root=project,
        name_token="e2e",
    )
    assert outcome.attachment is not None
    image_parts = agent_image_parts_from_prompt_attachments((outcome.attachment,))
    assert image_parts is not None

    async def scenario() -> None:
        writer = create_agent_session_runtime(
            session_dir=session_dir,
            model=_image_model(),
            persist=True,
        )
        session = await writer.create_session(cwd=str(project))
        await session.session_manager.append_message(
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="Describe this clipboard image"),
                    *image_parts,
                ],
                timestamp=1.0,
            )
        )
        await session.session_manager.dispose_runtime_profile()

        reader = _Runtime(session_dir)
        composition = bind_coding_continuity(reader, all_sessions=True)
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        preview = await composition.hub.preview(page.items[0].target)
        assert (
            "Assets",
            "Present (integrity checked on resume) · 1 objects · 26 bytes",
        ) in preview.sections[1].rows
        store = SessionBlobStore(tmp_path / "data", session.session_id)
        assert len(store.records) == 1
        assert store.read_bytes(store.records[0]) == clipboard_bytes
        await shutdown_coding_continuity(reader)

    asyncio.run(scenario())


def test_coding_resume_reports_unsafe_discovery_source(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    external_dir = tmp_path / "external"
    linked_dir = tmp_path / "linked"
    global_dir.mkdir()
    external_dir.mkdir()
    try:
        os.symlink(external_dir, linked_dir, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    runtime = _Runtime(global_dir)
    runtime.add_session_discovery_dir(linked_dir)
    composition = bind_coding_continuity(runtime, all_sessions=True)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert page.items == ()
        assert [item.code for item in page.provider_diagnostics] == [
            "coding_session_discovery_unsafe_root",
            "coding_continuity_bounded_catalog",
        ]
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_fingerprinted_exact_target_skips_preload_authority_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from loushang.harness.transcript import AgentTranscriptSessionCatalog

    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Resume once")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    def reject_full_preload(self, locator):
        del self, locator
        raise AssertionError("fingerprinted selection must not replay authority")

    monkeypatch.setattr(
        AgentTranscriptSessionCatalog,
        "load_authoritative_revision",
        reject_full_preload,
    )

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        lease = await composition.hub.prepare(page.items[0].target)
        await lease.abort()
        assert runtime.prepared == [str(transcript)]
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_excludes_current_session_from_resume(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Current prompt")],
    )
    runtime.refresh_session_index()
    current = object()
    runtime.current_session = current
    runtime.current_session_ref = str(transcript)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert page.items == ()
        assert runtime.prepared == []
        assert runtime.restored == []
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_excludes_current_session_before_page_slicing(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    current = tmp_path / "current.jsonl"
    history = tmp_path / "history.jsonl"
    write_agent_transcript_export(
        current,
        _header("z-current"),
        [_record("current-record", "Current prompt")],
    )
    write_agent_transcript_export(
        history,
        _header("a-history"),
        [_record("history-record", "Resume me")],
    )
    runtime.refresh_session_index()
    runtime.current_session = object()
    runtime.current_session_ref = str(current)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=1))
        assert [item.target.opaque_id for item in page.items] == ["a-history"]
        assert page.next_cursor is None
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_does_not_stale_index_for_active_session_appends(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    active = tmp_path / "active.jsonl"
    history = tmp_path / "history.jsonl"
    write_agent_transcript_export(
        active,
        _header("active"),
        [_record("active-record", "Current prompt")],
    )
    write_agent_transcript_export(
        history,
        _header("history"),
        [_record("history-record", "Resume me")],
    )
    runtime.refresh_session_index()
    index_mtime = runtime.session_catalog.index_path.stat().st_mtime_ns
    os.utime(active, ns=(index_mtime + 1, index_mtime + 1))
    runtime.current_session = object()
    runtime.current_session_ref = str(active)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert [item.target.opaque_id for item in page.items] == ["history"]
        assert page.aggregate_index_state == "fresh"
        assert page.provider_diagnostics == ()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_deletes_only_a_fresh_noncurrent_target(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Delete this session")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert await composition.hub.delete(page.items[0].target) is True
        assert runtime.deleted == [str(transcript)]
        assert transcript.exists() is False
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_lists_canonical_delete_targets_without_compatibility_roots(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Delete this session")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(
            ContinuityQuery(page_size=1, required_actions=("delete",))
        )
        assert [item.target.opaque_id for item in page.items] == ["session-1"]
        assert await composition.hub.delete(page.items[0].target) is True
        assert transcript.exists() is False
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_rejects_preserved_mtime_canonical_duplicate(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    first = tmp_path / "first.jsonl"
    duplicate = tmp_path / "duplicate.jsonl"
    write_agent_transcript_export(
        first,
        _header("shared"),
        [_record("first-record", "First content")],
    )
    runtime.refresh_session_index()
    index_modified = runtime.session_catalog.index_path.stat().st_mtime_ns
    write_agent_transcript_export(
        duplicate,
        _header("shared"),
        [_record("duplicate-record", "Different content")],
    )
    os.utime(duplicate, ns=(index_modified - 1, index_modified - 1))
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        assert page.items[0].status == "Conflict"
        with pytest.raises(ConflictedContinuityTargetError):
            await composition.hub.prepare(page.items[0].target)
        assert runtime.prepared == []
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_real_coding_runtime_delete_rechecks_path_level_authority(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority"
    project = tmp_path / "project"
    authority.mkdir()
    project.mkdir()
    original = authority / "original.jsonl"
    duplicate = authority / "duplicate.jsonl"
    write_agent_transcript_export(
        original,
        _header("shared", cwd=str(project)),
        [_record("original-record", "Original content")],
    )
    runtime = create_agent_session_runtime(
        session_dir=authority,
        model=_image_model(),
        persist=True,
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime, cwd=str(project))

    async def scenario() -> None:
        page = await composition.hub.query(
            ContinuityQuery(page_size=10, required_actions=("delete",))
        )
        assert [item.target.opaque_id for item in page.items] == ["shared"]
        write_agent_transcript_export(
            duplicate,
            _header("shared", cwd=str(project)),
            [_record("duplicate-record", "Different content")],
        )

        with pytest.raises(ValueError, match="Ambiguous session reference"):
            await composition.hub.delete(page.items[0].target)

        assert original.exists() is True
        assert duplicate.exists() is True
        assert runtime.session_catalog.is_tombstoned("shared") is False
        await shutdown_coding_continuity(runtime)
        await runtime.dispose_session_runtime()

    asyncio.run(scenario())


def test_coding_provider_cannot_delete_an_excluded_current_session(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Keep this session")],
    )
    runtime.refresh_session_index()
    runtime.current_session_ref = str(transcript)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert page.items == ()
        assert transcript.exists() is True
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_prepare_revalidates_selected_transcript_revision(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    header = _header("session-1")
    first = _record("record-1", "First message")
    write_agent_transcript_export(transcript, header, [first])
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        target = page.items[0].target
        write_agent_transcript_export(
            transcript,
            header,
            [
                first,
                _record("record-2", "Changed after listing", parent_id="record-1"),
            ],
        )

        with pytest.raises(StaleContinuityTargetError, match="changed"):
            await composition.hub.prepare(target)
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_uses_bounded_preview_for_a_stale_index(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    header = _header("session-1")
    first = _record("record-1", "First message")
    write_agent_transcript_export(transcript, header, [first])
    runtime.refresh_session_index()
    write_agent_transcript_export(
        transcript,
        header,
        [
            first,
            _record("record-2", "New hi", parent_id="record-1"),
        ],
    )
    index_modified = runtime.session_catalog.index_path.stat().st_mtime_ns
    if transcript.stat().st_mtime_ns <= index_modified:
        os.utime(
            transcript,
            ns=(transcript.stat().st_atime_ns, index_modified + 1),
        )
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        stale = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(stale.items) == 1
        assert stale.aggregate_index_state == "stale"
        assert stale.provider_diagnostics[0].code == (
            "coding_continuity_bounded_catalog"
        )
        lease = await composition.hub.prepare(stale.items[0].target)
        await lease.abort()
        await runtime.drain_session_index_flush()
        rebuilt = await composition.hub.query(ContinuityQuery(page_size=10))
        assert rebuilt.aggregate_index_state == "fresh"
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_reports_bounded_catalog_when_index_is_missing(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "session-1.jsonl",
        _header("session-1"),
        [_record("record-1", "Not scanned by query")],
    )
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))

        assert len(page.items) == 1
        assert page.items[0].title == "Not scanned by query"
        assert page.aggregate_index_state == "rebuilding"
        assert page.provider_diagnostics[0].code == (
            "coding_continuity_bounded_catalog"
        )
        assert not runtime.session_catalog.index_path.exists()
        await runtime.drain_session_index_flush()
        rebuilt = await composition.hub.query(ContinuityQuery(page_size=10))
        assert rebuilt.aggregate_index_state == "fresh"
        lease = await composition.hub.prepare(page.items[0].target)
        await lease.consume()
        assert runtime.restored == [str(tmp_path / "session-1.jsonl")]
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_prepare_revalidates_bounded_catalog_file_identity(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Bounded target")],
    )
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write("\n")

        with pytest.raises(StaleContinuityTargetError, match="changed"):
            await composition.hub.prepare(page.items[0].target)
        assert runtime.prepared == []
        await runtime.drain_session_index_flush()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_prepare_aborts_when_bounded_file_changes_during_prepare(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Bounded target")],
    )
    composition = bind_coding_continuity(runtime)

    def mutate() -> None:
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write("\n")

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        runtime.on_prepare = mutate

        with pytest.raises(StaleContinuityTargetError, match="being prepared"):
            await composition.hub.prepare(page.items[0].target)
        assert runtime.prepared == [str(transcript)]
        assert runtime.aborted == [str(transcript)]
        await runtime.drain_session_index_flush()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_hides_empty_sessions_from_resume(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "empty.jsonl",
        _header("empty"),
        [],
    )
    write_agent_transcript_export(
        tmp_path / "active.jsonl",
        _header("active"),
        [_record("record-1", "Visible prompt")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))

        assert [item.target.opaque_id for item in page.items] == ["active"]
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_continuity_shutdown_closes_hub_before_disposing_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "session-1.jsonl",
        _header("session-1"),
        [_record("record-1", "Explain the parser architecture")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    calls: list[str] = []
    original_close = composition.hub.close

    async def close_spy() -> None:
        calls.append("close")
        await original_close()

    original_dispose = composition.binder.dispose

    async def dispose_spy(binding: object) -> None:
        calls.append("dispose")
        await original_dispose(binding)

    def cleanup_spy() -> None:
        calls.append("owned-cleanup")

    monkeypatch.setattr(composition.hub, "close", close_spy)
    monkeypatch.setattr(composition.binder, "dispose", dispose_spy)
    composition.owned_cleanup = cleanup_spy

    asyncio.run(shutdown_coding_continuity(runtime))

    assert calls == ["close", "dispose", "owned-cleanup"]
    assert composition._shutdown
    asyncio.run(shutdown_coding_continuity(runtime))
    assert calls == ["close", "dispose", "owned-cleanup"]


def test_coding_continuity_failed_close_leaves_composition_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "session-1.jsonl",
        _header("session-1"),
        [_record("record-1", "Explain the parser architecture")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    disposed: list[object] = []
    original_dispose = composition.binder.dispose
    original_close = composition.hub.close

    async def dispose_spy(binding: object) -> None:
        disposed.append(binding)
        await original_dispose(binding)

    async def failing_close() -> None:
        raise RuntimeError("close failed")

    monkeypatch.setattr(composition.binder, "dispose", dispose_spy)
    monkeypatch.setattr(composition.hub, "close", failing_close)

    with pytest.raises(RuntimeError, match="close failed"):
        asyncio.run(composition.shutdown())
    assert not composition._shutdown
    assert disposed == []

    monkeypatch.setattr(composition.hub, "close", original_close)
    asyncio.run(shutdown_coding_continuity(runtime))
    assert composition._shutdown
    assert len(disposed) == 1
