"""Explicit v2 Binding facts for one ordinary UserMessage record.

These checks establish historical correspondence, not current admission or
native effect settlement. Transcript still owns the durable commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from loushang.ai.types import UserMessage
from loushang.coding.resume_activation_attempt_v2 import CodingActivationAttemptV2
from loushang.coding.resume_binding import (
    _FIELDS,
    CODING_RUNTIME_BINDING_METADATA_KEY,
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    freeze_coding_user_input,
    inspect_coding_runtime_binding,
)
from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

CODING_RUNTIME_BINDING_V2_METADATA_KEY = "coding.runtimeBindingV2"
CODING_RUNTIME_BINDING_V2_MAX_BYTES = 8192


def _encoded(value: object) -> bytes:
    return dump_json_value(
        value,
        name="Coding RuntimeBinding v2",
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@dataclass(frozen=True, slots=True)
class CodingRuntimeBindingV2(CodingRuntimeBindingV1):
    intent_digest: str = ""

    def __post_init__(self) -> None:
        CodingRuntimeBindingV1(
            self.attempt_id,
            self.input_id,
            self.record_id,
            self.session_id,
            self.original_leaf_id,
            self.ancestry_digest,
            self.subject_digest,
            self.origin_composition,
            self.planned_fingerprint,
            self.actual_fingerprint,
            self.payload_digest,
            self.difference_codes,
        )
        if (
            type(self.intent_digest) is not str
            or len(self.intent_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.intent_digest)
        ):
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
    # Reuse validation of the common fields only after requiring the exact v2
    # wire key, version and stored digest. A v1 fact cannot enter this decoder.
    common = {key: value for key, value in raw.items() if key != "intentDigest"}
    common["version"] = 1
    observation = inspect_coding_runtime_binding(
        {CODING_RUNTIME_BINDING_METADATA_KEY: common}
    )
    base = observation.binding
    if observation.status != "known" or type(base) is not CodingRuntimeBindingV1:
        raise ValueError("RuntimeBinding v2 common fields are invalid")
    digest = raw["intentDigest"]
    if type(digest) is not str:
        raise ValueError("RuntimeBinding v2 intent digest is invalid")
    return CodingRuntimeBindingV2(
        base.attempt_id,
        base.input_id,
        base.record_id,
        base.session_id,
        base.original_leaf_id,
        base.ancestry_digest,
        base.subject_digest,
        base.origin_composition,
        base.planned_fingerprint,
        base.actual_fingerprint,
        base.payload_digest,
        base.difference_codes,
        digest,
    )


def _require_intent(
    binding: CodingRuntimeBindingV2, intent: CodingActivationAttemptV2
) -> None:
    if (
        type(binding) is not CodingRuntimeBindingV2
        or type(intent) is not CodingActivationAttemptV2
    ):
        raise TypeError("RuntimeBinding v2 requires exact v2 Binding and intent values")
    if (
        binding.intent_digest != intent.digest
        or binding.attempt_id != intent.attempt_id
        or binding.input_id != intent.request_id
        or binding.session_id != intent.session_id
        or binding.original_leaf_id != intent.original_leaf_id
        or binding.ancestry_digest != intent.ancestry_digest
        or binding.planned_fingerprint != intent.plan_fingerprint
        or binding.actual_fingerprint != intent.epoch_fingerprint
        or binding.subject_digest != intent.subject_digest
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
    frozen_message = freeze_coding_user_input(message)
    if coding_user_payload_digest(frozen_message) != binding.payload_digest:
        raise ValueError(
            "RuntimeBinding v2 payload digest differs from the user message"
        )
    evidence = require_json_mapping(
        {} if resource_metadata is None else dict(resource_metadata),
        name="Resume v2 resource evidence",
    )
    if any(key.startswith("coding.runtimeBinding") for key in evidence):
        raise ValueError("Resume resource metadata conflicts with Binding version")
    record = AgentTranscriptRecordFactory(
        clock=lambda: created_at, id_factory=lambda: binding.record_id
    ).create(
        AGENT_MESSAGE_KIND,
        frozen_message,
        parent_id=intent.attempt_id,
        metadata={**evidence, **binding.to_message_metadata()},
    )
    validate_coding_resume_v2_user_record(record, intent=intent)
    return record


def validate_coding_resume_v2_user_record(
    record: AgentTranscriptRecord,
    *,
    intent: CodingActivationAttemptV2,
) -> CodingRuntimeBindingV2:
    if record.kind != AGENT_MESSAGE_KIND or type(record.payload) is not UserMessage:
        raise ValueError("RuntimeBinding v2 requires one ordinary UserMessage record")
    binding = decode_coding_runtime_binding_v2(record.metadata)
    _require_intent(binding, intent)
    if record.record_id != binding.record_id or record.parent_id != intent.attempt_id:
        raise ValueError("RuntimeBinding v2 stored record identity or parent differs")
    if coding_user_payload_digest(record.payload) != binding.payload_digest:
        raise ValueError("RuntimeBinding v2 stored user payload differs")
    return binding
