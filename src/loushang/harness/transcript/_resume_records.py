"""Construct fixed Resume records and check shared historical identity."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.json import JSONValue, dump_json_value
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import (
    AgentTranscriptPayload,
    AgentTranscriptRecord,
)
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

if TYPE_CHECKING:
    from loushang.harness.transcript.session import AgentTranscriptSession


def make_resume_record(
    kind: str,
    payload: AgentTranscriptPayload,
    *,
    record_id: str,
    parent_id: str | None,
    created_at: datetime,
    metadata: Mapping[str, JSONValue] | None = None,
) -> AgentTranscriptRecord:
    """Build a fixed-ID record through the existing Transcript factory."""
    factory = AgentTranscriptRecordFactory(
        clock=lambda: created_at, id_factory=lambda: record_id
    )
    return factory.create(kind, payload, parent_id=parent_id, metadata=metadata)


def freeze_user_message(message: UserMessage) -> UserMessage:
    """Detach mutable input through the Transcript payload codec."""
    if not isinstance(message, UserMessage):
        raise TypeError("Resume input requires a UserMessage")
    registry = create_agent_transcript_payload_registry()
    payload = registry.encode(AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message)
    frozen = registry.decode(AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, payload)
    if not isinstance(frozen, UserMessage):
        raise TypeError("Resume input codec did not preserve UserMessage")
    return frozen


def user_message_digest(
    message: UserMessage, *, digest_domain: bytes, require_externalized_images: bool
) -> str:
    """Hash the exact Transcript payload with the caller's historical domain."""
    if not isinstance(message, UserMessage):
        label = (
            "RuntimeBinding payload" if require_externalized_images else "Resume input"
        )
        raise TypeError(f"{label} requires a UserMessage")
    if require_externalized_images:
        content = message.content
        if isinstance(content, list) and any(
            isinstance(part, ImagePart) for part in content
        ):
            raise ValueError("RuntimeBinding image payload must be externalized first")
    payload = create_agent_transcript_payload_registry().encode(
        AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message
    )
    return sha256(digest_domain + canonical_binding_bytes(payload)).hexdigest()


def input_record_digest(record: AgentTranscriptRecord, *, digest_domain: bytes) -> str:
    """Hash the complete original binding record through the Transcript codec."""
    payload = ConversationJsonlRecordCodec(
        create_agent_transcript_payload_registry()
    ).encode_record(record)
    return sha256(
        digest_domain + canonical_binding_bytes(payload, name="Resume input lookup record")
    ).hexdigest()


def canonical_binding_bytes(value: object, *, name: str = "RuntimeBinding metadata") -> bytes:
    return dump_json_value(value, name=name, ensure_ascii=True, sort_keys=True).encode("utf-8")


class SelectedAncestry:
    def __init__(self, domain: bytes) -> None:
        self._digest = sha256(domain)
        self._parent_id: str | None = None
        self._seen: set[str] = set()

    def require_next(self, record: AgentTranscriptRecord, *, error: str) -> None:
        if record.parent_id != self._parent_id or record.record_id in self._seen:
            raise ValueError(error)
        self._seen.add(record.record_id)

    def advance(
        self, record: AgentTranscriptRecord, encode: Callable[[object], bytes]
    ) -> None:
        identity = encode({"recordId": record.record_id, "parentId": record.parent_id})
        self._digest.update(len(identity).to_bytes(4, "big"))
        self._digest.update(identity)
        self._parent_id = record.record_id

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def restore_verified_branch(
    transcript: AgentTranscriptSession,
    *,
    records: tuple[AgentTranscriptRecord, ...],
    selected_leaf_id: str | None,
    selected_records: tuple[AgentTranscriptRecord, ...],
    stale: Callable[[], Exception],
) -> None:
    """Select the verified leaf on an already acquired Writer."""
    if tuple(transcript.get_entries()) != records:
        raise stale()
    if selected_leaf_id is not None:
        transcript.branch(selected_leaf_id)
    if (
        transcript.leaf_id != selected_leaf_id
        or tuple(transcript.get_active_entries()) != selected_records
    ):
        raise stale()


def select_input_record(
    candidates: Sequence[AgentTranscriptRecord],
    *,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
    duplicate: Literal["unknown", "conflict"] = "conflict",
) -> AgentTranscriptRecord | Literal["unknown", "conflict"]:
    """Require one candidate and the exact bytes fixed for that input."""
    if not candidates:
        return "unknown"
    if len(candidates) != 1:
        return duplicate
    record = candidates[0]
    return record if digest(record) == expected_digest else "conflict"
