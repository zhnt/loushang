"""Product Worker discovery reads the real Transcript owner for every witness."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.ai.types import AssistantMessage, ToolCall, Usage
from loushang.coding.package_product_worker_discovery import (
    CodingWorkerTranscriptDiscoveryReader,
)
from loushang.coding.package_product_worker_policy import (
    CodingWorkerPolicySelectionError,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import ConversationHeader
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript import (
    AgentTranscriptDirectoryRuntime,
    write_agent_transcript_export,
)
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file
from loushang.harness.transcript.profile import AgentTranscriptProfile


def _write_session(
    path: Path, session_id: str, *, created_at: str = "2026-09-27T00:00:00Z"
) -> None:
    write_agent_transcript_export(
        path,
        ConversationHeader(
            conversation_id=session_id,
            version=1,
            created_at=created_at,
            metadata={"cwd": "/workspace/project"},
        ),
        [],
    )


def test_worker_discovery_rechecks_real_transcript_and_refuses_ambiguity(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    compatibility = tmp_path / "compatibility"
    canonical.mkdir()
    compatibility.mkdir()
    _write_session(canonical / "selected.jsonl", "selected")
    directory = AgentTranscriptDirectoryRuntime(session_dir=canonical)
    gate = PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl")
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory, gc_gate=gate, session_id="selected"
    )

    first = reader.current_discovery()
    assert reader.gc_gate is gate
    assert first.locator.conversation_id == "selected"
    assert first.conflicts == ()
    _write_session(compatibility / "conflict.jsonl", "selected")
    directory.add_session_discovery_dir(compatibility)
    with pytest.raises(CodingWorkerPolicySelectionError, match="discovery_sources_changed"):
        reader.current_discovery()
    assert not (tmp_path / "gc-gate.jsonl").exists()


def test_worker_discovery_refuses_missing_and_changed_transcript(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    path = canonical / "selected.jsonl"
    _write_session(path, "selected")
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=AgentTranscriptDirectoryRuntime(session_dir=canonical),
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl"),
        session_id="selected",
    )
    first = reader.current_discovery()
    path.unlink()
    with pytest.raises(CodingWorkerPolicySelectionError, match="discovery_missing"):
        reader.current_discovery()
    _write_session(path, "selected")
    second = reader.current_discovery()
    assert second.locator.conversation_id == "selected"
    assert second.locator.revision != first.locator.revision


def test_worker_discovery_refuses_real_transcript_conflict(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    compatibility = tmp_path / "compatibility"
    canonical.mkdir()
    compatibility.mkdir()
    _write_session(canonical / "selected.jsonl", "selected")
    _write_session(
        compatibility / "other.jsonl",
        "selected",
        created_at="2026-09-28T00:00:00Z",
    )
    directory = AgentTranscriptDirectoryRuntime(session_dir=canonical)
    directory.add_session_discovery_dir(compatibility)
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory,
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl"),
        session_id="selected",
    )
    with pytest.raises(CodingWorkerPolicySelectionError, match="discovery_conflict"):
        reader.current_discovery()
    assert not (tmp_path / "gc-gate.jsonl").exists()


def test_worker_discovery_maps_transcript_read_failure_to_stale_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    directory = AgentTranscriptDirectoryRuntime(session_dir=canonical)
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory,
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl"),
        session_id="selected",
    )

    def unreadable(*_args: object, **_kwargs: object) -> None:
        raise OSError("private transcript location")

    monkeypatch.setattr(directory, "list_discovered_session_summaries", unreadable)
    with pytest.raises(CodingWorkerPolicySelectionError) as error:
        reader.current_discovery()
    assert error.value.code == "coding_worker_session_discovery_unavailable"
    assert str(error.value) == error.value.code
    assert not (tmp_path / "gc-gate.jsonl").exists()


def _attached_reader(
    tmp_path: Path,
) -> tuple[
    SessionManager,
    AgentTranscriptDirectoryRuntime,
    CodingWorkerTranscriptDiscoveryReader,
]:
    session_dir = tmp_path / "sessions"
    manager = asyncio.run(
        SessionManager.new_with_composition(
            session_dir=session_dir,
            cwd=str(tmp_path),
            session_id="attached",
            defer_materialization=False,
        )
    )
    path = manager.get_session_file()
    assert path is not None
    directory = AgentTranscriptDirectoryRuntime(session_dir=session_dir)
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory,
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl"),
        session_id="attached",
        selected_session_file=path,
        attached_session=manager,
    )
    return manager, directory, reader


def test_attached_worker_discovery_allows_owner_append_with_stable_revision(
    tmp_path: Path,
) -> None:
    manager, _, reader = _attached_reader(tmp_path)
    first = reader.current_discovery()
    asyncio.run(manager.append_custom_entry("worker-test", {"step": 1}))
    second = reader.current_discovery()
    assert second.locator.revision == first.locator.revision
    assert second.locator.revision.startswith("attached-v1:")


def test_attached_worker_discovery_allows_committed_tool_call(tmp_path: Path) -> None:
    manager, _, reader = _attached_reader(tmp_path)
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="worker-query-turn",
                        name="worker_query_symbol",
                        arguments={"symbol": "review"},
                    )
                ],
                api="test",
                provider="test",
                model="direct-worker",
                response_id=None,
                usage=Usage(
                    input=0,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=0,
                    cost={},
                ),
                stop_reason="toolUse",
                error_message=None,
                timestamp=0.0,
            )
        )
    )
    path = manager.get_session_file()
    assert path is not None
    _, disk_records = load_agent_transcript_file(path, read_only=True)
    codec = ConversationJsonlRecordCodec(AgentTranscriptProfile.default().payload_codecs)
    assert [codec.encode_record(record) for record in disk_records] == [
        codec.encode_record(record) for record in manager.get_entries()
    ]
    assert reader.current_discovery().locator.revision.startswith("attached-v1:")


def test_attached_worker_discovery_resume_keeps_locator_identity(tmp_path: Path) -> None:
    manager, directory, reader = _attached_reader(tmp_path)
    original_revision = reader.current_discovery().locator.revision
    asyncio.run(manager.append_custom_entry("worker-test", {"step": 1}))
    path = manager.get_session_file()
    assert path is not None
    resumed = asyncio.run(SessionManager.load(path))
    resumed_reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory,
        gc_gate=reader.gc_gate,
        session_id="attached",
        selected_session_file=path,
        attached_session=resumed,
    )
    assert resumed_reader.current_discovery().locator.revision == original_revision


def test_attached_worker_discovery_refuses_external_append(tmp_path: Path) -> None:
    manager, _, reader = _attached_reader(tmp_path)
    path = manager.get_session_file()
    assert path is not None
    external = asyncio.run(SessionManager.load(path))
    asyncio.run(external.append_custom_entry("external-test", {"step": 1}))
    with pytest.raises(CodingWorkerPolicySelectionError, match="attached_transcript_changed"):
        reader.current_discovery()


def test_attached_worker_discovery_refuses_file_replacement(tmp_path: Path) -> None:
    manager, _, reader = _attached_reader(tmp_path)
    path = manager.get_session_file()
    assert path is not None
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(CodingWorkerPolicySelectionError, match="attached_transcript_changed"):
        reader.current_discovery()


def test_attached_worker_discovery_refuses_changed_source(tmp_path: Path) -> None:
    _, directory, reader = _attached_reader(tmp_path)
    additional = tmp_path / "additional"
    additional.mkdir()
    directory.add_session_discovery_dir(additional)
    with pytest.raises(CodingWorkerPolicySelectionError, match="discovery_sources_changed"):
        reader.current_discovery()


def test_attached_worker_discovery_refuses_same_id_copy(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    compatibility = tmp_path / "compatibility"
    compatibility.mkdir()
    manager = asyncio.run(
        SessionManager.new_with_composition(
            session_dir=session_dir,
            cwd=str(tmp_path),
            session_id="attached",
            defer_materialization=False,
        )
    )
    path = manager.get_session_file()
    assert path is not None
    directory = AgentTranscriptDirectoryRuntime(session_dir=session_dir)
    directory.add_session_discovery_dir(compatibility)
    reader = CodingWorkerTranscriptDiscoveryReader(
        directory=directory,
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-gate.jsonl"),
        session_id="attached",
        selected_session_file=path,
        attached_session=manager,
    )
    assert reader.current_discovery().aliases == ()
    (compatibility / "copy.jsonl").write_bytes(path.read_bytes())
    with pytest.raises(CodingWorkerPolicySelectionError, match="discovery_conflict"):
        reader.current_discovery()
