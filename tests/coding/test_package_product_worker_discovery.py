"""Product Worker discovery reads the real Transcript owner for every witness."""

from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.package_product_worker_discovery import (
    CodingWorkerTranscriptDiscoveryReader,
)
from loushang.coding.package_product_worker_policy import (
    CodingWorkerPolicySelectionError,
)
from loushang.harness.conversation import ConversationHeader
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript import (
    AgentTranscriptDirectoryRuntime,
    write_agent_transcript_export,
)


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
