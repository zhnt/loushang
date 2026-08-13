from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from loushang.ai.json_codec import deserialize_content_part, deserialize_message
from loushang.ai.types import ImagePart, TextPart
from loushang.foundation.json import JSONValue, JsonValueError, require_json_mapping
from loushang.harness.conversation import (
    CURRENT_CONVERSATION_FORMAT_VERSION,
    CommandExecutionRecord,
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationKey,
    ConversationRecord,
    ConversationRepository,
    ConversationSnapshot,
    ConversationStore,
    OpaquePayload,
)
from loushang.harness.journal import journal_file_lock
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.types import (
    AgentTranscriptRecord,
    ApplicationDeliveryMode,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
)

CURRENT_SESSION_VERSION = 3
LEGACY_SESSION_OPAQUE_KIND = "loushang.session.opaque"
MigrationDisposition = Literal["migrated", "already_conversation_jsonl"]


class SessionV3MigrationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        path: Path | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.line_number = line_number


@dataclass(frozen=True)
class SessionV3MigrationResult:
    header: ConversationHeader
    records: tuple[AgentTranscriptRecord, ...]
    disposition: MigrationDisposition


@dataclass(frozen=True)
class SessionV3ImportResult:
    source: SessionV3MigrationResult
    key: ConversationKey
    snapshot: ConversationSnapshot[ConversationHeader, AgentTranscriptRecord]


def convert_session_v3_snapshot(
    header_value: Mapping[str, object],
    entry_values: Sequence[Mapping[str, object]],
) -> SessionV3MigrationResult:
    """Convert decoded current Session v3 mappings without touching storage."""

    header = _convert_session_header(header_value)
    records: list[AgentTranscriptRecord] = []
    for index, entry_value in enumerate(entry_values, start=2):
        try:
            entry = _object(entry_value, name="Session v3 entry")
            records.append(_convert_session_entry(entry))
        except SessionV3MigrationError as exc:
            if exc.line_number is not None:
                raise
            raise SessionV3MigrationError(
                str(exc),
                code=exc.code,
                line_number=index,
            ) from exc
        except Exception as exc:
            raise SessionV3MigrationError(
                "Session v3 entry is invalid",
                code="invalid_session_entry",
                line_number=index,
            ) from exc
    result = SessionV3MigrationResult(
        header=header,
        records=tuple(records),
        disposition="migrated",
    )
    _validate_conversation_jsonl_snapshot(result.header, result.records)
    return result


async def import_session_v3_file(
    path: str | Path,
    *,
    store: ConversationStore[ConversationHeader, AgentTranscriptRecord],
    key: ConversationKey,
    operation_id: str,
) -> SessionV3ImportResult:
    """Read a legacy source and atomically create a Conversation JSONL target."""

    source = await asyncio.to_thread(read_session_v3_file, path)
    if source.header.conversation_id != key.conversation_id:
        raise SessionV3MigrationError(
            "Import key and converted conversation id do not match",
            code="conversation_identity_mismatch",
            path=Path(path),
        )
    snapshot = await store.create(
        key,
        source.header,
        source.records,
        operation_id=operation_id,
    )
    return SessionV3ImportResult(source=source, key=key, snapshot=snapshot)


def read_session_v3_file(path: str | Path) -> SessionV3MigrationResult:
    """Read and convert Session v3 without modifying the source file."""

    target = Path(path)
    with journal_file_lock(target, "shared"):
        raw = _read_session_text(target)
        values = _parse_jsonl(raw, path=target)
        return _convert_or_load_conversation_jsonl(values, path=target)


def is_conversation_jsonl_file(path: str | Path) -> bool:
    """Return whether the first nonblank line identifies a Conversation JSONL."""

    target = Path(path)
    try:
        with target.open(encoding="utf-8") as stream:
            first_line = next((line for line in stream if line.strip()), None)
    except OSError:
        return False
    if first_line is None:
        return False
    try:
        value = json.loads(first_line, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(value, dict) and value.get("type") == "conversation"


def _read_session_text(target: Path) -> str:
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SessionV3MigrationError(
            "Session file could not be read",
            code="session_read_failed",
            path=target,
        ) from exc


def _convert_or_load_conversation_jsonl(
    values: tuple[dict[str, JSONValue], ...],
    *,
    path: Path,
) -> SessionV3MigrationResult:
    if not values:
        raise SessionV3MigrationError(
            "Session file is empty",
            code="empty_session_file",
            path=path,
        )
    discriminator = values[0].get("type")
    if discriminator == "conversation":
        return _load_conversation_jsonl_snapshot(values, path=path)
    if discriminator != "session":
        raise SessionV3MigrationError(
            "File is neither Session v3 nor Conversation JSONL",
            code="unsupported_conversation_format",
            path=path,
            line_number=1,
        )
    try:
        result = convert_session_v3_snapshot(values[0], values[1:])
    except SessionV3MigrationError as exc:
        raise SessionV3MigrationError(
            str(exc),
            code=exc.code,
            path=path,
            line_number=exc.line_number,
        ) from exc
    return result


def _load_conversation_jsonl_snapshot(
    values: tuple[dict[str, JSONValue], ...],
    *,
    path: Path,
) -> SessionV3MigrationResult:
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(
        create_agent_transcript_payload_registry()
    )
    try:
        header = header_codec.decode_header(values[0])
        records = tuple(
            cast(AgentTranscriptRecord, record_codec.decode_record(value))
            for value in values[1:]
        )
        _validate_conversation_jsonl_snapshot(header, records)
    except Exception as exc:
        raise SessionV3MigrationError(
            "Conversation JSONL file is invalid",
            code="invalid_conversation_jsonl",
            path=path,
        ) from exc
    return SessionV3MigrationResult(
        header=header,
        records=records,
        disposition="already_conversation_jsonl",
    )


def _convert_session_header(value: Mapping[str, object]) -> ConversationHeader:
    try:
        header = _object(value, name="Session v3 header")
        if _text(header, "type") != "session":
            raise ValueError("Session v3 header must have type='session'")
        version = _integer(header, "version")
        if version != CURRENT_SESSION_VERSION:
            raise SessionV3MigrationError(
                "Only the current Loushang Session v3 format can be migrated",
                code="unsupported_session_version",
                line_number=1,
            )
        conversation_id = _text(header, "id")
        created_at = _text(header, "timestamp")
        cwd = _text(header, "cwd")
        parent_session = _optional_text(header, "parentSession", missing=None)
        source: dict[str, JSONValue] = {
            "format": "loushang.session",
            "version": CURRENT_SESSION_VERSION,
        }
        metadata: dict[str, JSONValue] = {
            "cwd": cwd,
            "loushang.session.source": source,
        }
        if parent_session is not None:
            metadata["parentSession"] = parent_session
        return ConversationHeader(
            conversation_id=conversation_id,
            version=CURRENT_CONVERSATION_FORMAT_VERSION,
            created_at=created_at,
            metadata=metadata,
        )
    except SessionV3MigrationError:
        raise
    except Exception as exc:
        raise SessionV3MigrationError(
            "Session v3 header is invalid",
            code="invalid_session_header",
            line_number=1,
        ) from exc


def _convert_session_entry(value: dict[str, JSONValue]) -> AgentTranscriptRecord:
    entry_type = _text(value, "type")
    record_id = _text(value, "id")
    parent_id = _optional_text(value, "parentId")
    created_at = _text(value, "timestamp")

    if entry_type == "message":
        kind, payload = _convert_message_entry(value, record_id=record_id)
    elif entry_type == "thinking_level_change":
        kind = THINKING_SELECTION_KIND
        payload = ThinkingSelectionSnapshot(level=_text(value, "thinkingLevel"))
    elif entry_type == "model_change":
        kind = MODEL_SELECTION_KIND
        payload = ModelSelectionSnapshot(
            provider=_text(value, "provider"),
            endpoint_id=_text(value, "endpointId"),
            model_id=_text(value, "modelId"),
        )
    elif entry_type == "compaction":
        kind = CONTEXT_COMPACTION_CHECKPOINT_KIND
        payload = ContextCompactionCheckpoint(
            summary=_string(value, "summary"),
            first_kept_record_id=_text(value, "firstKeptEntryId"),
            tokens_before=_non_negative_integer(value, "tokensBefore"),
            details=value.get("details"),
            from_hook=_optional_bool(value, "fromHook", missing=None),
        )
    elif entry_type == "branch_summary":
        kind = CONTEXT_BRANCH_SUMMARY_KIND
        payload = BranchContextSummary(
            from_record_id=_text(value, "fromId"),
            summary=_string(value, "summary"),
            details=value.get("details"),
            from_hook=_optional_bool(value, "fromHook", missing=None),
        )
    elif entry_type == "custom":
        kind = EXTENSION_DATA_KIND
        payload = ExtensionData(
            extension_type=_text(value, "customType"),
            data=value.get("data"),
        )
    elif entry_type == "custom_message":
        kind = APPLICATION_MESSAGE_KIND
        payload = _application_message_from_entry(
            value,
            record_id=record_id,
            timestamp=_timestamp_from_iso(created_at),
        )
    elif entry_type == "label":
        kind = RECORD_ANNOTATION_PATCH_KIND
        label = value.get("label")
        if label is not None and not isinstance(label, str):
            raise TypeError("Session label must be a string or null")
        payload = RecordAnnotationPatch(
            target_record_id=_text(value, "targetId"),
            namespace="display.label",
            operation="remove" if label is None else "set",
            value=label,
        )
    elif entry_type == "session_info":
        kind = CONVERSATION_METADATA_PATCH_KIND
        name = value.get("name")
        if name is not None and not isinstance(name, str):
            raise TypeError("Session name must be a string or null")
        payload = ConversationMetadataPatch(
            values={} if name is None else {"name": name},
            removed_keys=("name",) if name is None else (),
        )
    else:
        kind = LEGACY_SESSION_OPAQUE_KIND
        payload = OpaquePayload(value)

    return cast(
        AgentTranscriptRecord,
        ConversationRecord(
            record_id=record_id,
            parent_id=parent_id,
            kind=kind,
            payload_version=STANDARD_PAYLOAD_VERSION,
            created_at=created_at,
            payload=payload,
        ),
    )


def _convert_message_entry(
    entry: dict[str, JSONValue],
    *,
    record_id: str,
) -> tuple[str, object]:
    message = _object(_field(entry, "message"), name="Session v3 message")
    role = _text(message, "role")
    if role in {"user", "assistant", "toolResult"}:
        return AGENT_MESSAGE_KIND, deserialize_message(message)
    if role == "bashExecution":
        return COMMAND_EXECUTION_KIND, CommandExecutionRecord(
            command=_string(message, "command"),
            output=_string(message, "output"),
            exit_code=_optional_integer(message, "exitCode", missing=None),
            cancelled=_boolean(message, "cancelled"),
            truncated=_boolean(message, "truncated"),
            full_output_path=_optional_string(
                message,
                "fullOutputPath",
                missing=None,
            ),
            exclude_from_context=_optional_bool(
                message,
                "excludeFromContext",
                missing=False,
            )
            is True,
            metadata=_optional_mapping(message, "metadata"),
        )
    if role in {"custom", "application"}:
        timestamp = _number(message, "timestamp")
        return APPLICATION_MESSAGE_KIND, _application_message_from_entry(
            message,
            record_id=record_id,
            timestamp=timestamp,
        )
    if role == "branchSummary":
        return CONTEXT_BRANCH_SUMMARY_KIND, BranchContextSummary(
            from_record_id=_text(message, "fromId"),
            summary=_string(message, "summary"),
        )
    return LEGACY_SESSION_OPAQUE_KIND, OpaquePayload(entry)


def _application_message_from_entry(
    value: Mapping[str, JSONValue],
    *,
    record_id: str,
    timestamp: float,
) -> ApplicationMessage:
    content_value = _field(value, "content")
    if isinstance(content_value, str):
        content: str | list[TextPart | ImagePart] = content_value
    elif isinstance(content_value, list):
        content = []
        for raw_part in content_value:
            part = deserialize_content_part(
                _object(raw_part, name="Session v3 application content part")
            )
            if not isinstance(part, TextPart | ImagePart):
                raise TypeError(
                    "Session v3 application messages support text/image parts only"
                )
            content.append(part)
    else:
        raise TypeError("Session v3 application content is invalid")
    application_message_id = value.get("applicationMessageId")
    if application_message_id is None:
        application_message_id = f"loushang.session.v3:{record_id}"
    if not isinstance(application_message_id, str):
        raise TypeError("Session v3 application message id must be a string")
    origin = value.get("origin", "loushang.session.v3")
    delivery_mode = value.get("deliveryMode", "direct")
    return ApplicationMessage(
        application_message_id=application_message_id,
        custom_type=_text(value, "customType"),
        content=content,
        timestamp=timestamp,
        display=_optional_bool(value, "display", missing=True) is not False,
        details=value.get("details"),
        origin=cast(str, origin),
        delivery_mode=cast(ApplicationDeliveryMode, delivery_mode),
    )


def _validate_conversation_jsonl_snapshot(
    header: ConversationHeader,
    records: tuple[AgentTranscriptRecord, ...],
) -> None:
    registry = create_agent_transcript_payload_registry()
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(registry)
    header_codec.encode_header(header)
    for record in records:
        record_codec.encode_record(record)
    ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode="strict",
    )


def _parse_jsonl(
    raw: str,
    *,
    path: Path,
) -> tuple[dict[str, JSONValue], ...]:
    values: list[dict[str, JSONValue]] = []
    lines = raw.splitlines()
    last_nonblank_line = None
    for line_number, line in enumerate(lines, start=1):
        if line.strip():
            last_nonblank_line = line_number
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line, parse_constant=_reject_json_constant)
            values.append(
                require_json_mapping(decoded, name=f"JSONL line {line_number}")
            )
        except (json.JSONDecodeError, JsonValueError, ValueError) as exc:
            if line_number == last_nonblank_line and not raw.endswith(("\n", "\r")):
                continue
            raise SessionV3MigrationError(
                "Session file contains invalid strict JSON",
                code="invalid_session_json",
                path=path,
                line_number=line_number,
            ) from exc
    return tuple(values)


def _reject_json_constant(token: str):
    raise ValueError(f"non-standard JSON constant: {token}")


_MISSING = object()


def _object(value: object, *, name: str) -> dict[str, JSONValue]:
    return require_json_mapping(value, name=name)


def _field(value: Mapping[str, JSONValue], key: str) -> JSONValue:
    if key not in value:
        raise KeyError(f"missing field {key!r}")
    return value[key]


def _string(value: Mapping[str, JSONValue], key: str) -> str:
    field = _field(value, key)
    if not isinstance(field, str):
        raise TypeError(f"field {key!r} must be a string")
    return field


def _text(value: Mapping[str, JSONValue], key: str) -> str:
    field = _string(value, key)
    if not field.strip():
        raise ValueError(f"field {key!r} must not be empty")
    return field


def _optional_string(
    value: Mapping[str, JSONValue],
    key: str,
    *,
    missing: object = _MISSING,
) -> str | None:
    field = value.get(key, missing)
    if field is _MISSING:
        raise KeyError(f"missing field {key!r}")
    if field is None:
        return None
    if not isinstance(field, str):
        raise TypeError(f"field {key!r} must be a string or null")
    return field


def _optional_text(
    value: Mapping[str, JSONValue],
    key: str,
    *,
    missing: object = _MISSING,
) -> str | None:
    field = _optional_string(value, key, missing=missing)
    if field is not None and not field.strip():
        raise ValueError(f"field {key!r} must not be empty")
    return field


def _integer(value: Mapping[str, JSONValue], key: str) -> int:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError(f"field {key!r} must be an integer")
    return field


def _non_negative_integer(value: Mapping[str, JSONValue], key: str) -> int:
    field = _integer(value, key)
    if field < 0:
        raise ValueError(f"field {key!r} must be non-negative")
    return field


def _optional_integer(
    value: Mapping[str, JSONValue],
    key: str,
    *,
    missing: object = _MISSING,
) -> int | None:
    field = value.get(key, missing)
    if field is _MISSING:
        raise KeyError(f"missing field {key!r}")
    if field is None:
        return None
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError(f"field {key!r} must be an integer or null")
    return field


def _boolean(value: Mapping[str, JSONValue], key: str) -> bool:
    field = _field(value, key)
    if type(field) is not bool:
        raise TypeError(f"field {key!r} must be a boolean")
    return field


def _optional_bool(
    value: Mapping[str, JSONValue],
    key: str,
    *,
    missing: object = _MISSING,
) -> bool | None:
    field = value.get(key, missing)
    if field is _MISSING:
        raise KeyError(f"missing field {key!r}")
    if field is not None and type(field) is not bool:
        raise TypeError(f"field {key!r} must be a boolean or null")
    return cast(bool | None, field)


def _number(value: Mapping[str, JSONValue], key: str) -> float:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int | float):
        raise TypeError(f"field {key!r} must be a number")
    return float(field)


def _optional_mapping(value: Mapping[str, JSONValue], key: str) -> dict[str, JSONValue]:
    if key not in value:
        return {}
    return require_json_mapping(value[key], name=key)


def _timestamp_from_iso(value: str) -> float:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Session timestamp must include a timezone")
    return timestamp.astimezone(UTC).timestamp()


__all__ = [
    "CURRENT_SESSION_VERSION",
    "LEGACY_SESSION_OPAQUE_KIND",
    "MigrationDisposition",
    "SessionV3MigrationError",
    "SessionV3ImportResult",
    "SessionV3MigrationResult",
    "convert_session_v3_snapshot",
    "import_session_v3_file",
    "is_conversation_jsonl_file",
    "read_session_v3_file",
]
