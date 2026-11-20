"""Construct fixed Resume records and check shared historical identity."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.json import JSONValue, dump_json_value
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
    from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
    from loushang.coding.resume.binding import CodingRuntimeBindingV1


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


def matches_intent(
    binding: CodingRuntimeBindingV1,
    attempt: CodingActivationAttemptV1,
    *,
    check_session: bool,
) -> bool:
    """Compare common fields after the caller selects the version and parent."""
    return not (
        binding.attempt_id != attempt.attempt_id
        or binding.input_id != attempt.request_id
        or (check_session and binding.session_id != attempt.session_id)
        or binding.original_leaf_id != attempt.original_leaf_id
        or binding.ancestry_digest != attempt.ancestry_digest
        or binding.planned_fingerprint != attempt.plan_fingerprint
        or binding.actual_fingerprint != attempt.epoch_fingerprint
        or binding.subject_digest != attempt.subject_digest
    )


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


def canonical_binding_bytes(value: object, *, name: str = "RuntimeBinding metadata") -> bytes:
    return dump_json_value(value, name=name, ensure_ascii=True, sort_keys=True).encode("utf-8")
