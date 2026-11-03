from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.composition_provenance import CODING_COMPOSITION_HEADER_KEY
from loushang.coding.continuity import bind_coding_continuity
from loushang.coding.product_plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
)
from loushang.coding.runtime import agent_session_runtime as runtime_module
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.harness.continuity import ContinuityQuery
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    write_agent_transcript_export,
)
from loushang.harness.transcript.jsonl_file import AgentTranscriptFileError
from loushang.harnesstui.conversation.agent_binding import agent_session_history_records


def _fixture(tmp_path, *, owned=False):
    path = tmp_path / "history.jsonl"
    capability = CODING_CAPABILITY_PROFILE.snapshot().to_json()
    capability["capabilities"] = []
    header = ConversationHeader(
        conversation_id="history", version=1, created_at="2026-10-12T00:00:00Z",
        metadata={
            "cwd": str(tmp_path / "removed-workspace"),
            CODING_CAPABILITY_PROFILE_METADATA_KEY: capability,
            CODING_COMPOSITION_HEADER_KEY: {
                "version": 1, "setId": "retired-coding-set", "planFingerprint": "a" * 64,
            },
        },
    )
    records = [ConversationRecord(
        record_id=identity, parent_id=parent, kind=AGENT_MESSAGE_KIND,
        payload_version=1, created_at="2026-10-12T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=1.0),
    ) for identity, parent, text in [
        ("root", None, "Root"), ("left", "root", "Left"), ("right", "root", "Right"),
    ]]
    write_agent_transcript_export(path, header, records)

    def forbidden_factory(*args, **kwargs):
        pytest.fail("history must not construct a Product Session")

    owner = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=forbidden_factory, owned_transcripts=owned,
    )
    return owner, path, header, records


@pytest.mark.parametrize("reference", ["path", "identity"])
@pytest.mark.parametrize("owned", [False, pytest.param(
    True, marks=pytest.mark.skipif(sys.platform != "linux", reason="Linux owned transcripts"),
)])
def test_embedded_history_preserves_selected_path_without_writer_or_cwd_repair(tmp_path, reference, owned):
    owner, path, header, _ = _fixture(tmp_path, owned=owned)
    before = path.read_bytes()
    before_files = {item.name: item.read_bytes() for item in tmp_path.iterdir()}

    async def scenario():
        try:
            history = await owner.preview_resume_history(
                path if reference == "path" else "history", selected_leaf_id="left",
            )
            assert history.header_preview.header == header
            assert history.header_preview.product_identity == "coding"
            assert history.header_preview.composition is not None
            assert history.header_preview.composition.set_id == "retired-coding-set"
            assert history.status == "preview"
            assert [record.record_id for record in history.selected_records] == ["root", "left"]
            # The original terminal history projector needs only the detached
            # selected records, never an AgentSession or live Tool resolver.
            rendered = agent_session_history_records(history.selected_records)
            assert [record.text for record in rendered] == ["Root", "Left"]
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()
        with pytest.raises(RuntimeError, match="coding_resume_history_closed"):
            await owner.preview_resume_history(path)

    asyncio.run(scenario())
    assert path.read_bytes() == before
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before_files


@pytest.mark.parametrize("read_mode", ["snapshot", "recent_page"])
def test_embedded_history_rejects_changed_source_at_delivery(tmp_path, monkeypatch, read_mode):
    owner, path, header, records = _fixture(tmp_path)
    reader_name = "read_coding_resume_snapshot" if read_mode == "snapshot" else "read_coding_resume_recent_page"
    original = getattr(runtime_module, reader_name)
    preview = owner.preview_resume_history if read_mode == "snapshot" else owner.preview_resume_recent_page

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        write_agent_transcript_export(path, header, records[:-1])
        return result

    monkeypatch.setattr(runtime_module, reader_name, changed)

    async def scenario():
        try:
            with pytest.raises(ValueError, match="coding_resume_history_stale"):
                await preview(path)
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_real_embedded_continuity_preview_uses_runtime_history_owner(tmp_path, monkeypatch):
    owner, path, _, _ = _fixture(tmp_path)
    before = path.read_bytes()
    owner.refresh_session_index()
    composition = bind_coding_continuity(owner)
    original = runtime_module.read_coding_resume_snapshot
    calls = 0

    def observe(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "read_coding_resume_snapshot", observe)

    async def scenario():
        try:
            reference = composition.hub.reference()
            page = await reference.query(ContinuityQuery(page_size=10))
            assert len(page.items) == 1
            preview = await reference.preview(page.items[0].target)
            assert "Right" in preview.sections[0].text
            assert "Left" not in preview.sections[0].text
            assert not preview.stale
            assert calls == 1
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())
    assert path.read_bytes() == before


@pytest.mark.parametrize("read_mode", ["snapshot", "recent_page"])
def test_embedded_history_root_retains_cancelled_waiter_and_fences_delivery(tmp_path, monkeypatch, read_mode):
    owner, path, _, _ = _fixture(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    reader_name = "read_coding_resume_snapshot" if read_mode == "snapshot" else "read_coding_resume_recent_page"
    original = getattr(runtime_module, reader_name)
    preview = owner.preview_resume_history if read_mode == "snapshot" else owner.preview_resume_recent_page
    calls = 0

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        try:
            if not release.wait(5):
                raise RuntimeError("test read was not released")
            return original(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(runtime_module, reader_name, blocked)

    async def scenario():
        first = asyncio.create_task(preview(path))
        second = None
        close = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert len(owner._resume_history_reads) == 1
            assert not finished.is_set()
            second = asyncio.create_task(preview(path))
            async with asyncio.timeout(5):
                while len(owner._resume_history_reads) != 2:
                    await asyncio.sleep(0)
            with pytest.raises(RuntimeError, match="coding_resume_history_capacity_exceeded"):
                await preview(path)
            close = asyncio.create_task(owner.dispose_session_runtime())
            async with asyncio.timeout(5):
                while not owner._resume_history_closed:
                    await asyncio.sleep(0)
            done, _ = await asyncio.wait({close}, timeout=0.05)
            assert not done
            close.cancel()  # Root cancellation also waits for native settlement.
            with pytest.raises(RuntimeError, match="coding_resume_history_closed"):
                await preview(path)
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            if second is not None:
                with pytest.raises(RuntimeError, match="coding_resume_history_closed"):
                    await second
            if close is not None:
                with pytest.raises(asyncio.CancelledError):
                    await close
            await owner.dispose_session_runtime()
        assert not owner._resume_history_reads
        assert finished.is_set()
        assert calls == 2
        assert owner.current_session is None

    asyncio.run(scenario())


@pytest.mark.parametrize("budget", [True, 0, 64 * 1024 * 1024 + 1])
def test_embedded_history_rejects_invalid_budget_before_discovery(tmp_path, budget):
    owner, _, _, _ = _fixture(tmp_path)

    async def scenario():
        try:
            with pytest.raises(ValueError, match="byte budget"):
                await owner.preview_resume_history("missing", max_bytes=budget)
            assert not owner._resume_history_reads
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


def test_embedded_history_default_reads_selected_transcript_above_one_mib(tmp_path):
    owner, path, header, _ = _fixture(tmp_path)
    records = [ConversationRecord(
        record_id=f"record-{index}",
        parent_id=None if index == 0 else f"record-{index - 1}",
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-10-12T00:00:01Z",
        payload=UserMessage(role="user", content="x" * 1024, timestamp=1.0),
    ) for index in range(1800)]
    write_agent_transcript_export(path, header, records)
    assert 1024 * 1024 < path.stat().st_size < 8 * 1024 * 1024
    owner.refresh_session_index()

    async def scenario():
        try:
            history = await owner.preview_resume_history(path)
            assert history.selected_records[-1].record_id == "record-1799"
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("reference", ["path", "identity"])
def test_root_recent_page_is_detached_unverified_history(tmp_path, reference):
    owner, path, header, _ = _fixture(tmp_path)
    before = path.read_bytes()
    before_names = {item.name for item in tmp_path.iterdir()}

    async def scenario():
        try:
            page = await owner.preview_resume_recent_page(path if reference == "path" else "history")
            assert page.header_preview.header == header
            assert page.status == "unverified_tail_preview"
            assert not hasattr(page, "selected_records")
            assert [record.record_id for record in page.records] == ["root", "left", "right"]
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()
        with pytest.raises(RuntimeError, match="coding_resume_history_closed"):
            await owner.preview_resume_recent_page(path)

    asyncio.run(scenario())
    assert path.read_bytes() == before
    assert {item.name for item in tmp_path.iterdir()} == before_names


def test_root_recent_page_handles_history_above_snapshot_budget(tmp_path, monkeypatch):
    owner, path, header, _ = _fixture(tmp_path)
    records = [ConversationRecord(
        record_id=f"record-{index}", parent_id=None if index == 0 else f"record-{index - 1}",
        kind=AGENT_MESSAGE_KIND, payload_version=1, created_at="2026-10-12T00:00:01Z",
        payload=UserMessage(role="user", content="x" * 1024, timestamp=1.0),
    ) for index in range(12000)]
    write_agent_transcript_export(path, header, records)
    assert path.stat().st_size > 8 * 1024 * 1024
    before = path.stat()
    owner.refresh_session_index()
    composition = bind_coding_continuity(owner)
    before_names = {item.name for item in tmp_path.iterdir()}
    original_reader = runtime_module.read_coding_resume_recent_page
    reads = []

    def observed(*args, **kwargs):
        assert owner._resume_history_reads  # The native Root retains this IO.
        reads.append(args[0])
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "read_coding_resume_recent_page", observed)

    async def scenario():
        try:
            page = await owner.preview_resume_recent_page(path)
            assert page.status == "unverified_tail_preview"
            assert page.records[-1].record_id == "record-11999"
            assert len(page.records) < 12000
            assert page.bytes_read <= 2 * 64 * 1024
            assert owner.current_session is None
            reference = composition.hub.reference()
            try:
                candidates = await reference.query(ContinuityQuery(page_size=10))
                assert len(candidates.items) == 1
                preview = await reference.preview(candidates.items[0].target)
                assert not preview.stale
                rows = [row for section in preview.sections for row in section.rows]
                assert ("Recent history", "Unverified tail preview") in rows
                assert any(section.text for section in preview.sections)
                assert reads == [path, path]
                assert owner.current_session is None
            finally:
                reference.release()
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert {item.name for item in tmp_path.iterdir()} == before_names


def test_resume_startup_fully_reads_a_transcript_above_eight_mib(
    tmp_path,
):
    owner, path, header, _ = _fixture(tmp_path)
    records = [ConversationRecord(
        record_id=f"record-{index}",
        parent_id=None if index == 0 else f"record-{index - 1}",
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-10-12T00:00:01Z",
        payload=UserMessage(role="user", content="x" * 1024, timestamp=1.0),
    ) for index in range(12000)]
    write_agent_transcript_export(path, header, records)
    assert path.stat().st_size > 8 * 1024 * 1024
    before = path.read_bytes()
    owner.refresh_session_index()

    async def scenario():
        try:
            startup = await owner.preview_resume_startup(path)
            assert startup.status == "preview"
            assert startup.selected_records[-1].record_id == "record-11999"
            assert len(startup.records) == 12000
            assert owner.current_session is None
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())
    assert path.read_bytes() == before


def test_resume_startup_falls_back_only_when_the_full_budget_is_exceeded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, path, _, _ = _fixture(tmp_path)

    async def oversized(*_args, **_kwargs):
        raise AgentTranscriptFileError(
            "too large", path=path, code="session_file_too_large"
        )

    monkeypatch.setattr(owner, "preview_resume_history", oversized)

    async def scenario() -> None:
        try:
            startup = await owner.preview_resume_startup(path)
            assert startup.status == "unverified_tail_preview"
            assert startup.records[-1].record_id == "right"
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("segment_bytes", [True, 0, 1024 * 1024 + 1])
def test_root_recent_page_refuses_invalid_budget_before_discovery(tmp_path, segment_bytes):
    owner, _, _, _ = _fixture(tmp_path)

    async def scenario():
        try:
            with pytest.raises(ValueError, match="segment budget"):
                await owner.preview_resume_recent_page(tmp_path / "absent.jsonl", segment_bytes=segment_bytes)
            assert not owner._resume_history_reads
        finally:
            await owner.dispose_session_runtime()

    asyncio.run(scenario())
