from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.harness.conversation import (
    ConversationKey,
    MemoryConversationStore,
    OpaquePayload,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    LEGACY_SESSION_OPAQUE_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    THINKING_SELECTION_KIND,
    ApplicationMessage,
    ContextCompactionCheckpoint,
    SessionV3MigrationError,
    import_session_v3_file,
    read_session_v3_file,
)


def _header(*, version: int = 3):
    return {
        "type": "session",
        "version": version,
        "id": "session-1",
        "timestamp": "2026-07-16T00:00:00Z",
        "cwd": "/workspace/project",
        "parentSession": "/sessions/parent.jsonl",
    }


def _entry(entry_type: str, record_id: str, parent_id: str | None, **fields):
    return {
        "type": entry_type,
        "id": record_id,
        "parentId": parent_id,
        "timestamp": f"2026-07-16T00:00:{int(record_id[1:]):02d}Z",
        **fields,
    }


def _current_entries():
    entries = [
        _entry(
            "message",
            "e1",
            None,
            message={"role": "user", "content": "Hello", "timestamp": 1.0},
        ),
        _entry(
            "message",
            "e2",
            "e1",
            message={
                "role": "bashExecution",
                "command": "pwd",
                "output": "/workspace/project",
                "exitCode": 0,
                "cancelled": False,
                "truncated": False,
                "fullOutputPath": None,
                "timestamp": 2.0,
                "excludeFromContext": False,
            },
        ),
        _entry(
            "thinking_level_change",
            "e3",
            "e2",
            thinkingLevel="high",
        ),
        _entry(
            "model_change",
            "e4",
            "e3",
            provider="provider",
            modelId="model",
            endpointId="endpoint",
        ),
        _entry(
            "compaction",
            "e5",
            "e4",
            summary="Earlier context",
            firstKeptEntryId="e2",
            tokensBefore=100,
            details={"reason": "automatic"},
            fromHook=False,
        ),
        _entry(
            "branch_summary",
            "e6",
            "e5",
            fromId="e4",
            summary="Alternative branch",
            details=None,
            fromHook=None,
        ),
        _entry(
            "custom",
            "e7",
            "e6",
            customType="extension.state",
            data={"enabled": True},
        ),
        _entry(
            "custom_message",
            "e8",
            "e7",
            customType="notice",
            content="Extension notice",
            details={"priority": 1},
            display=True,
        ),
        _entry(
            "label",
            "e9",
            "e8",
            targetId="e2",
            label="Workspace",
        ),
        _entry("session_info", "e10", "e9", name="Migration run"),
        _entry(
            "future_extension_entry",
            "e11",
            "e10",
            nested={"unknown": [1, True, None]},
        ),
    ]
    return entries


def _write_jsonl(path: Path, values) -> None:
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )


def _import(path: Path):
    store = MemoryConversationStore(record_id=lambda record: record.record_id)
    key = ConversationKey("imported", "session-1")
    result = asyncio.run(
        import_session_v3_file(
            path,
            store=store,
            key=key,
            operation_id="import:session-1",
        )
    )
    return result, store


def test_current_session_v3_migrates_all_standard_kinds_and_preserves_unknown(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    source_entries = _current_entries()
    _write_jsonl(path, [_header(), *source_entries])
    original = path.read_bytes()

    imported, store = _import(path)
    result = imported.source

    assert result.disposition == "migrated"
    assert result.header.conversation_id == "session-1"
    assert result.header.version == 1
    assert result.header.metadata["cwd"] == "/workspace/project"
    assert result.header.metadata["parentSession"] == "/sessions/parent.jsonl"
    assert result.header.metadata["loushang.session.source"] == {
        "format": "loushang.session",
        "version": 3,
    }
    assert tuple(record.kind for record in result.records) == (
        AGENT_MESSAGE_KIND,
        COMMAND_EXECUTION_KIND,
        THINKING_SELECTION_KIND,
        MODEL_SELECTION_KIND,
        CONTEXT_COMPACTION_CHECKPOINT_KIND,
        CONTEXT_BRANCH_SUMMARY_KIND,
        EXTENSION_DATA_KIND,
        APPLICATION_MESSAGE_KIND,
        RECORD_ANNOTATION_PATCH_KIND,
        CONVERSATION_METADATA_PATCH_KIND,
        LEGACY_SESSION_OPAQUE_KIND,
    )
    assert isinstance(result.records[4].payload, ContextCompactionCheckpoint)
    application = result.records[7].payload
    assert isinstance(application, ApplicationMessage)
    assert application.application_message_id == "loushang.session.v3:e8"
    opaque = result.records[-1].payload
    assert isinstance(opaque, OpaquePayload)
    assert opaque.value == source_entries[-1]

    assert imported.snapshot.header == result.header
    assert imported.snapshot.records == result.records
    assert path.read_bytes() == original

    repeated = asyncio.run(
        import_session_v3_file(
            path,
            store=store,
            key=imported.key,
            operation_id="import:session-1",
        )
    )
    assert repeated.snapshot == imported.snapshot
    assert path.read_bytes() == original


def test_corrupted_known_entry_fails_without_modifying_source(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    values = [
        _header(),
        _entry(
            "model_change",
            "e1",
            None,
            provider="provider",
        ),
    ]
    _write_jsonl(path, values)
    original = path.read_bytes()

    with pytest.raises(SessionV3MigrationError) as error:
        read_session_v3_file(path)

    assert error.value.code == "invalid_session_entry"
    assert error.value.line_number == 2
    assert path.read_bytes() == original


def test_unsupported_session_version_fails_without_modifying_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    _write_jsonl(path, [_header(version=2)])
    original = path.read_bytes()

    with pytest.raises(SessionV3MigrationError) as error:
        read_session_v3_file(path)

    assert error.value.code == "unsupported_session_version"
    assert path.read_bytes() == original


def test_invalid_json_fails_without_modifying_source(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(json.dumps(_header()) + "\n{not-json}\n", encoding="utf-8")
    original = path.read_bytes()

    with pytest.raises(SessionV3MigrationError) as error:
        read_session_v3_file(path)

    assert error.value.code == "invalid_session_json"
    assert error.value.line_number == 2
    assert path.read_bytes() == original


def test_partial_tail_is_skipped_during_session_v3_migration(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    valid_entry = _current_entries()[0]
    path.write_text(
        json.dumps(_header()) + "\n" + json.dumps(valid_entry) + "\n{",
        encoding="utf-8",
    )
    original = path.read_bytes()

    result, _ = _import(path)

    assert result.source.disposition == "migrated"
    assert tuple(record.record_id for record in result.source.records) == ("e1",)
    assert path.read_bytes() == original
