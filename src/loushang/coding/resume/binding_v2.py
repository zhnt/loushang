"""Explicit v2 Binding facts for one ordinary UserMessage record.

These checks establish historical correspondence, not current admission or
native effect settlement. Transcript still owns the durable commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from functools import partial

from loushang.ai.types import UserMessage
from loushang.coding.resume.activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume.binding import (
    _FIELDS,
    CodingRuntimeBindingV1,
    _decode_runtime_binding_fields,
    _require_v1_budget,
    coding_user_payload_digest,
    freeze_coding_user_input,
    matches_intent,
)
from loushang.foundation.json import JSONValue
from loushang.harness.resume_effects import is_resume_digest
from loushang.harness.transcript import _resume_records as _records
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord

CODING_RUNTIME_BINDING_V2_METADATA_KEY = "coding.runtimeBindingV2"
CODING_RUNTIME_BINDING_V2_MAX_BYTES = 8192


_encoded = partial(_records.canonical_binding_bytes, name="Coding RuntimeBinding v2")


@dataclass(frozen=True, slots=True)
class CodingRuntimeBindingV2(CodingRuntimeBindingV1):
    intent_digest: str = ""

    def __post_init__(self) -> None:
        CodingRuntimeBindingV1._validate_v1_fields(self)
        _require_v1_budget(CodingRuntimeBindingV1._document(self))
        if not is_resume_digest(self.intent_digest):
            raise ValueError(
                "RuntimeBinding v2 requires the exact stored intent digest"
            )
        if len(_encoded(self._document())) > CODING_RUNTIME_BINDING_V2_MAX_BYTES:
            raise ValueError("RuntimeBinding v2 exceeds its 8 KiB byte budget")

    def _document(self) -> dict[str, JSONValue]:
        document = CodingRuntimeBindingV1._document(self)
        document["version"] = 2
        document["intentDigest"] = self.intent_digest
        return document

    def to_message_metadata(self) -> dict[str, JSONValue]:
        return {CODING_RUNTIME_BINDING_V2_METADATA_KEY: self._document()}


def decode_coding_runtime_binding_v2(
    metadata: Mapping[str, object],
) -> CodingRuntimeBindingV2:
    reserved = {key for key in metadata if key.startswith("coding.runtimeBinding")}
    if reserved != {CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
        raise ValueError("RuntimeBinding v2 requires one explicit metadata version")
    raw = metadata[CODING_RUNTIME_BINDING_V2_METADATA_KEY]
    if not isinstance(raw, Mapping) or set(raw) != _FIELDS | {"intentDigest"}:
        raise ValueError("RuntimeBinding v2 fields are invalid")
    if type(raw.get("version")) is not int or raw["version"] != 2:
        raise ValueError("RuntimeBinding v2 version is unsupported")
    # The exact v2 wire envelope precedes the common field and v1 budget checks.
    common = {key: value for key, value in raw.items() if key != "intentDigest"}
    common["version"] = 1
    base = _decode_runtime_binding_fields(common)
    digest = raw["intentDigest"]
    if type(digest) is not str:
        raise ValueError("RuntimeBinding v2 intent digest is invalid")
    return CodingRuntimeBindingV2(
        **{item.name: getattr(base, item.name) for item in fields(base)},
        intent_digest=digest,
    )


def _require_intent(
    binding: CodingRuntimeBindingV2, intent: CodingActivationAttemptV2
) -> None:
    if (
        type(binding) is not CodingRuntimeBindingV2
        or type(intent) is not CodingActivationAttemptV2
    ):
        raise TypeError("RuntimeBinding v2 requires exact v2 Binding and intent values")
    if binding.intent_digest != intent.digest or not matches_intent(
        binding, intent, check_session=True
    ):
        raise ValueError("RuntimeBinding v2 does not match the exact frozen intent")
    if binding.record_id == intent.attempt_id:
        raise ValueError(
            "RuntimeBinding v2 input and intent require distinct record ids"
        )


def prepare_coding_resume_v2_user_record(
    binding: CodingRuntimeBindingV2,
    message: UserMessage,
    *,
    intent: CodingActivationAttemptV2,
    created_at: datetime,
    resource_metadata: Mapping[str, JSONValue] | None = None,
) -> AgentTranscriptRecord:
    _require_intent(binding, intent)
    return _records.make_resume_user_record(
        freeze_coding_user_input(message),
        binding,
        parent_id=intent.attempt_id,
        created_at=created_at,
        resource_metadata=resource_metadata,
        evidence_name="Resume v2 resource evidence",
        metadata_conflict="Resume resource metadata conflicts with Binding version",
        reserved_prefix="coding.runtimeBinding",
        digest=coding_user_payload_digest,
        payload_error="RuntimeBinding v2 payload digest differs from the user message",
        validate=lambda record: validate_coding_resume_v2_user_record(record, intent=intent),
    )


def validate_coding_resume_v2_user_record(
    record: AgentTranscriptRecord,
    *,
    intent: CodingActivationAttemptV2,
) -> CodingRuntimeBindingV2:
    payload = _require_v2_user_payload(record)
    binding = decode_coding_runtime_binding_v2(record.metadata)
    _require_decoded_v2_binding(record, binding, payload=payload, intent=intent)
    return binding


def _require_v2_user_payload(record: AgentTranscriptRecord) -> UserMessage:
    if record.kind != AGENT_MESSAGE_KIND or type(record.payload) is not UserMessage:
        raise ValueError("RuntimeBinding v2 requires one ordinary UserMessage record")
    return record.payload


def _require_decoded_v2_binding(
    record: AgentTranscriptRecord,
    binding: CodingRuntimeBindingV2,
    *,
    payload: UserMessage,
    intent: CodingActivationAttemptV2,
) -> None:
    _require_intent(binding, intent)
    if record.record_id != binding.record_id or record.parent_id != intent.attempt_id:
        raise ValueError("RuntimeBinding v2 stored record identity or parent differs")
    if coding_user_payload_digest(payload) != binding.payload_digest:
        raise ValueError("RuntimeBinding v2 stored user payload differs")
