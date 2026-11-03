from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.composition_provenance import CODING_COMPOSITION_HEADER_KEY
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.product_plan import (
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_RUNTIME_PROFILE_METADATA_KEY,
)
from loushang.coding.resume_binding import (
    CODING_RUNTIME_BINDING_METADATA_KEY,
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    prepare_coding_resume_user_record,
)
from loushang.coding.resume_composition_comparison import (
    compare_coding_resume_composition,
)
from loushang.coding.resume_history import (
    inspect_coding_resume_header,
    read_coding_resume_header,
    read_coding_resume_snapshot,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import AGENT_MESSAGE_KIND
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    load_agent_transcript_file,
    load_agent_transcript_file_with_content_digest,
    write_agent_transcript_export,
)
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)


def test_readonly_resume_header_survives_retired_composition_and_profile_change(
    tmp_path,
) -> None:
    async def create() -> object:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            composition_set="coding-minimal",
            defer_materialization=False,
        )
        try:
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    assert path is not None
    header, records = load_agent_transcript_file(path, read_only=True)
    metadata = deepcopy(dict(header.metadata))
    metadata[CODING_COMPOSITION_HEADER_KEY] = {
        "version": 1,
        "setId": "retired-coding-set",
        "planFingerprint": "a" * 64,
    }
    capability = metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
    assert isinstance(capability, dict)
    capability["capabilities"] = []
    write_agent_transcript_export(path, replace(header, metadata=metadata), records)
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()}

    preview = read_coding_resume_header(path)

    assert preview.header.conversation_id == header.conversation_id
    assert preview.product_identity == "coding"
    assert preview.composition is not None
    assert preview.composition.set_id == "retired-coding-set"
    assert preview.composition.plan_fingerprint == "a" * 64
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()} == before


def test_readonly_resume_header_marks_missing_composition_as_legacy_unknown(
    tmp_path,
) -> None:
    async def create() -> object:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        try:
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    assert path is not None

    preview = read_coding_resume_header(path)

    assert preview.product_identity == "coding"
    assert preview.composition is None

    metadata = dict(preview.header.metadata)
    metadata.pop(CODING_RUNTIME_PROFILE_METADATA_KEY)
    metadata.pop(CODING_CAPABILITY_PROFILE_METADATA_KEY)
    unknown = inspect_coding_resume_header(
        replace(preview.header, metadata=metadata)
    )
    assert unknown.product_identity == "unknown"

    foreign = deepcopy(dict(preview.header.metadata))
    capability = foreign[CODING_CAPABILITY_PROFILE_METADATA_KEY]
    assert isinstance(capability, dict)
    capability["productId"] = "another-product"
    with pytest.raises(ValueError, match="another-product"):
        inspect_coding_resume_header(replace(preview.header, metadata=foreign))

    with path.open("ab") as stream:
        stream.write(b'{"type":')
    before = path.read_bytes()
    history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert history.status == "preview"
    assert history.records == ()
    assert compare_coding_resume_composition(
        history, resolve_coding_composition_set("coding-standard"),
    ).status == "legacy_unknown"
    assert path.read_bytes() == before
    with pytest.raises(AgentTranscriptFileError, match="read budget"):
        read_coding_resume_snapshot(path, max_bytes=1)
    assert path.read_bytes() == before


@pytest.mark.parametrize(("extension_type", "data", "expected_status"), [
    ("coding.activation-attempt/v1", {"version": 1}, "invalid"),
    ("coding.activation-attempt/v2", {"version": 2}, "invalid"),
])
def test_readonly_history_keeps_unrecognized_activation_intent_viewable(
    tmp_path, extension_type, data, expected_status,
) -> None:
    async def create() -> object:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path),
            defer_materialization=False,
        )
        try:
            await manager.append_custom_entry(extension_type, data)
            return manager.session_file
        finally:
            await manager.dispose_runtime_profile()

    path = asyncio.run(create())
    assert path is not None
    before = path.read_bytes()
    history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert history.activation_status == expected_status
    assert len(history.selected_records) == 1
    assert path.read_bytes() == before


def test_readonly_snapshot_selects_one_parent_linked_history_path(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "branches.jsonl"
    header = ConversationHeader(
        conversation_id="session-1", version=1, created_at="2026-10-12T00:00:00Z",
    )

    def message(record_id: str, parent_id: str | None) -> ConversationRecord:
        return ConversationRecord(
            record_id=record_id,
            parent_id=parent_id,
            kind=AGENT_MESSAGE_KIND,
            payload_version=1,
            created_at="2026-10-12T00:00:00Z",
            payload=UserMessage(role="user", content=record_id, timestamp=1.0),
        )

    write_agent_transcript_export(path, header, [
        message("root", None),
        message("left", "root"),
        message("right", "root"),
    ])
    before = path.read_bytes()

    preview = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)

    assert [record.record_id for record in preview.records] == ["root", "left", "right"]
    assert [record.record_id for record in preview.selected_records] == ["root", "right"]
    assert preview.selected_leaf_id == "right"
    assert preview.binding_status == "none"
    assert len(preview.selected_ancestry_digest) == 64
    assert preview.source_fingerprint == session_file_authority_fingerprint(path)
    assert path.read_bytes() == before

    left = read_coding_resume_snapshot(
        path, max_bytes=1024 * 1024, selected_leaf_id="left",
    )
    assert [record.record_id for record in left.selected_records] == ["root", "left"]
    assert left.selected_leaf_id == "left"
    assert left.selected_ancestry_digest != preview.selected_ancestry_digest
    assert left.source_fingerprint == preview.source_fingerprint
    with pytest.raises(ValueError, match="source changed"):
        read_coding_resume_snapshot(
            path, max_bytes=1024 * 1024,
            expected_source_fingerprint="stale",
        )
    with pytest.raises(ValueError):
        read_coding_resume_snapshot(
            path, max_bytes=1024 * 1024, selected_leaf_id="missing",
        )

    original_load = load_agent_transcript_file_with_content_digest

    def change_after_read(*args, **kwargs):
        result = original_load(*args, **kwargs)
        with path.open("ab") as stream:
            stream.write(b"\n")
        return result

    monkeypatch.setattr(
        "loushang.coding.resume_history.load_agent_transcript_file_with_content_digest",
        change_after_read,
    )
    with pytest.raises(ValueError, match="source changed"):
        read_coding_resume_snapshot(path, max_bytes=1024 * 1024)


def test_readonly_snapshot_reports_selected_binding_without_blocking_corrupt_history(
    tmp_path,
) -> None:
    path = tmp_path / "binding.jsonl"
    header = ConversationHeader(
        conversation_id="session-1", version=1, created_at="2026-10-12T00:00:00Z",
    )
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = CodingRuntimeBindingV1(
        attempt_id="attempt-1", input_id="input-1", record_id="bound-1",
        session_id=header.conversation_id, original_leaf_id=None,
        ancestry_digest="a" * 64, subject_digest="b" * 64,
        origin_composition=None, planned_fingerprint="c" * 64,
        actual_fingerprint="d" * 64,
        payload_digest=coding_user_payload_digest(message),
    )
    bound = prepare_coding_resume_user_record(
        binding, message, commit_parent_id=None,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    write_agent_transcript_export(path, header, [bound])
    before = path.read_bytes()

    preview = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert preview.binding_status == "bound"
    assert preview.binding == binding
    assert path.read_bytes() == before

    corrupt = replace(
        bound,
        metadata={CODING_RUNTIME_BINDING_METADATA_KEY: {"version": 1}},
    )
    write_agent_transcript_export(path, header, [corrupt])
    preview = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert preview.binding_status == "invalid"
    assert preview.binding is None
    assert preview.selected_ancestry_digest is None
    assert preview.selected_records == (corrupt,)

    future = replace(
        bound,
        metadata={CODING_RUNTIME_BINDING_METADATA_KEY: {"version": 2}},
    )
    write_agent_transcript_export(path, header, [future])
    preview = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
    assert preview.binding_status == "unknown_version"
    assert preview.binding is None
    assert preview.selected_records == (future,)
