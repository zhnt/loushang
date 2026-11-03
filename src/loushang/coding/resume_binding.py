"""Coding-owned historical RuntimeBinding metadata for one resumed user input.

This value records what an activation selected. It does not grant present
authority, prove effect settlement, or admit a Model or Tool invocation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

from .composition_provenance import CodingCompositionProvenanceV1

CODING_RUNTIME_BINDING_METADATA_KEY = "coding.runtimeBindingV1"
CODING_RUNTIME_BINDING_VERSION = 1
CODING_RUNTIME_BINDING_MAX_BYTES = 4096

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIFFERENCE_CODE = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({
    "version", "attemptId", "inputId", "recordId", "sessionId",
    "originalLeafId", "ancestryDigest", "subjectDigest", "originEvidence",
    "plannedFingerprint", "actualFingerprint", "payloadDigest",
    "differenceCodes",
})


@dataclass(frozen=True, slots=True)
class CodingRuntimeBindingV1:
    """Bounded, redacted fact co-committed with the first resumed UserMessage."""

    attempt_id: str
    input_id: str
    record_id: str
    session_id: str
    original_leaf_id: str | None
    ancestry_digest: str
    subject_digest: str
    origin_composition: CodingCompositionProvenanceV1 | None
    planned_fingerprint: str
    actual_fingerprint: str
    payload_digest: str
    difference_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("attempt_id", "input_id", "record_id", "session_id"):
            _require_identifier(getattr(self, name), name=name)
        if self.original_leaf_id is not None:
            _require_identifier(self.original_leaf_id, name="original leaf id")
        for name in (
            "ancestry_digest", "subject_digest", "planned_fingerprint",
            "actual_fingerprint", "payload_digest",
        ):
            _require_digest(getattr(self, name), name=name)
        origin = self.origin_composition
        if origin is not None:
            if not isinstance(origin, CodingCompositionProvenanceV1):
                raise TypeError("RuntimeBinding origin composition is invalid")
            _require_identifier(origin.set_id, name="origin composition set")
            _require_digest(origin.plan_fingerprint, name="origin plan fingerprint")
        if type(self.difference_codes) is not tuple or len(self.difference_codes) > 16:
            raise ValueError("RuntimeBinding difference codes exceed the limit")
        if self.difference_codes != tuple(sorted(set(self.difference_codes))):
            raise ValueError("RuntimeBinding difference codes must be sorted and unique")
        if any(
            type(code) is not str or _DIFFERENCE_CODE.fullmatch(code) is None
            for code in self.difference_codes
        ):
            raise ValueError("RuntimeBinding difference codes must be redacted identifiers")
        if len(_canonical_bytes(self._document())) > CODING_RUNTIME_BINDING_MAX_BYTES:
            raise ValueError("RuntimeBinding metadata exceeds its byte budget")

    def to_message_metadata(self) -> dict[str, JSONValue]:
        return {CODING_RUNTIME_BINDING_METADATA_KEY: self._document()}

    def _document(self) -> dict[str, JSONValue]:
        origin: dict[str, JSONValue]
        if self.origin_composition is None:
            origin = {"kind": "legacy_unknown"}
        else:
            origin = {
                "kind": "composition",
                "setId": self.origin_composition.set_id,
                "planFingerprint": self.origin_composition.plan_fingerprint,
            }
        return {
            "version": CODING_RUNTIME_BINDING_VERSION,
            "attemptId": self.attempt_id,
            "inputId": self.input_id,
            "recordId": self.record_id,
            "sessionId": self.session_id,
            "originalLeafId": self.original_leaf_id,
            "ancestryDigest": self.ancestry_digest,
            "subjectDigest": self.subject_digest,
            "originEvidence": origin,
            "plannedFingerprint": self.planned_fingerprint,
            "actualFingerprint": self.actual_fingerprint,
            "payloadDigest": self.payload_digest,
            "differenceCodes": list(self.difference_codes),
        }


@dataclass(frozen=True, slots=True)
class CodingRuntimeBindingObservation:
    status: Literal["absent", "known", "unknown_version"]
    binding: CodingRuntimeBindingV1 | None = None


@dataclass(frozen=True, slots=True)
class CodingRuntimeBindingPathProjection:
    """Last relevant Binding and structural digest of one selected path.

    The digest covers record and parent IDs only. Callers must separately
    validate the source revision and record content before execution.
    """

    status: Literal["none", "bound", "unknown_version"]
    ancestry_digest: str
    binding: CodingRuntimeBindingV1 | None = None
    record_id: str | None = None


def project_coding_runtime_binding_path(
    records: Iterable[AgentTranscriptRecord], *, current_session_id: str,
) -> CodingRuntimeBindingPathProjection:
    """Project historical epoch evidence, without granting current authority.

    The caller must supply the complete, selected root-to-leaf ancestry. A copied
    source Session Binding in a fork remains origin evidence, not a target epoch.
    An unknown later schema makes activation unavailable until understood.
    """

    _require_identifier(current_session_id, name="current Session id")
    status: Literal["none", "bound", "unknown_version"] = "none"
    selected_binding: CodingRuntimeBindingV1 | None = None
    selected_record_id: str | None = None
    ancestry = hashlib.sha256(b"loushang.coding.resume-ancestry/v1\0")
    previous_id: str | None = None
    seen: set[str] = set()
    for record in records:
        if record.parent_id != previous_id or record.record_id in seen:
            raise ValueError("RuntimeBinding projection requires a complete parent-linked path")
        seen.add(record.record_id)
        previous_id = record.record_id
        identity = _canonical_bytes({
            "recordId": record.record_id, "parentId": record.parent_id,
        })
        ancestry.update(len(identity).to_bytes(4, "big"))
        ancestry.update(identity)
        observation = inspect_coding_runtime_binding(record.metadata)
        if observation.status == "absent":
            continue
        if record.kind != AGENT_MESSAGE_KIND or not isinstance(record.payload, UserMessage):
            raise ValueError("RuntimeBinding requires an agent UserMessage record")
        if observation.status == "unknown_version":
            status = "unknown_version"
            selected_binding = None
            selected_record_id = record.record_id
            continue
        observed_binding = observation.binding
        if observed_binding is None:
            raise ValueError("RuntimeBinding known schema has no binding")
        binding = validate_coding_runtime_binding_record(
            record, expected_session_id=observed_binding.session_id,
        )
        if binding.session_id == current_session_id and status != "unknown_version":
            status = "bound"
            selected_binding = binding
            selected_record_id = record.record_id
    return CodingRuntimeBindingPathProjection(
        status, ancestry.hexdigest(),
        binding=selected_binding, record_id=selected_record_id,
    )


def inspect_coding_runtime_binding(
    metadata: Mapping[str, object],
) -> CodingRuntimeBindingObservation:
    """Decode known metadata; leave later schema versions inert in history."""

    if any(
        key.startswith("coding.runtimeBinding")
        and key != CODING_RUNTIME_BINDING_METADATA_KEY
        for key in metadata
    ):
        return CodingRuntimeBindingObservation("unknown_version")
    if CODING_RUNTIME_BINDING_METADATA_KEY not in metadata:
        return CodingRuntimeBindingObservation("absent")
    raw = metadata[CODING_RUNTIME_BINDING_METADATA_KEY]
    if not isinstance(raw, Mapping):
        raise ValueError("RuntimeBinding metadata is malformed")
    version = raw.get("version")
    if type(version) is int and version > CODING_RUNTIME_BINDING_VERSION:
        return CodingRuntimeBindingObservation("unknown_version")
    if type(version) is not int or version != CODING_RUNTIME_BINDING_VERSION:
        raise ValueError("RuntimeBinding metadata version is invalid")
    if set(raw) != _FIELDS:
        raise ValueError("RuntimeBinding metadata fields are invalid")
    document = require_json_mapping(dict(raw), name="RuntimeBinding metadata")
    origin = document["originEvidence"]
    if not isinstance(origin, dict):
        raise ValueError("RuntimeBinding origin evidence is invalid")
    provenance: CodingCompositionProvenanceV1 | None
    if origin == {"kind": "legacy_unknown"}:
        provenance = None
    elif set(origin) == {"kind", "setId", "planFingerprint"} and origin.get("kind") == "composition":
        provenance = CodingCompositionProvenanceV1(
            _text(origin, "setId"), _text(origin, "planFingerprint"),
        )
    else:
        raise ValueError("RuntimeBinding origin evidence is invalid")
    differences = document["differenceCodes"]
    if not isinstance(differences, list) or any(
        type(value) is not str for value in differences
    ):
        raise ValueError("RuntimeBinding difference codes are invalid")
    binding = CodingRuntimeBindingV1(
        attempt_id=_text(document, "attemptId"),
        input_id=_text(document, "inputId"),
        record_id=_text(document, "recordId"),
        session_id=_text(document, "sessionId"),
        original_leaf_id=_optional_text(document, "originalLeafId"),
        ancestry_digest=_text(document, "ancestryDigest"),
        subject_digest=_text(document, "subjectDigest"),
        origin_composition=provenance,
        planned_fingerprint=_text(document, "plannedFingerprint"),
        actual_fingerprint=_text(document, "actualFingerprint"),
        payload_digest=_text(document, "payloadDigest"),
        difference_codes=cast(tuple[str, ...], tuple(differences)),
    )
    return CodingRuntimeBindingObservation("known", binding)


def freeze_coding_user_input(message: UserMessage) -> UserMessage:
    """Detach mutable caller content using the original Transcript codec."""

    if not isinstance(message, UserMessage):
        raise TypeError("Resume input requires a UserMessage")
    registry = create_agent_transcript_payload_registry()
    payload = registry.encode(AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message)
    frozen = registry.decode(
        AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, payload,
    )
    if not isinstance(frozen, UserMessage):
        raise TypeError("Resume input codec did not preserve UserMessage")
    return frozen


def coding_user_input_digest(message: UserMessage) -> str:
    """Freeze admitted input bytes before image externalization, without writes."""

    if not isinstance(message, UserMessage):
        raise TypeError("Resume input requires a UserMessage")
    payload = create_agent_transcript_payload_registry().encode(
        AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message,
    )
    return hashlib.sha256(
        b"loushang.coding.resume-input/v1\0" + _canonical_bytes(payload)
    ).hexdigest()


def coding_user_payload_digest(message: UserMessage) -> str:
    """Digest the exact persisted UserMessage payload, including image refs."""

    if not isinstance(message, UserMessage):
        raise TypeError("RuntimeBinding payload requires a UserMessage")
    content = message.content
    if isinstance(content, list) and any(isinstance(part, ImagePart) for part in content):
        raise ValueError("RuntimeBinding image payload must be externalized first")
    payload = create_agent_transcript_payload_registry().encode(
        AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message,
    )
    return hashlib.sha256(
        b"loushang.coding.resume-user-message/v1\0" + _canonical_bytes(payload)
    ).hexdigest()


def prepare_coding_resume_user_record(
    binding: CodingRuntimeBindingV1,
    message: UserMessage,
    *,
    commit_parent_id: str | None,
    created_at: datetime,
    resource_metadata: Mapping[str, JSONValue] | None = None,
) -> AgentTranscriptRecord:
    """Freeze Binding and Resource evidence before one ordinary message commit."""

    if not isinstance(binding, CodingRuntimeBindingV1):
        raise TypeError("RuntimeBinding record requires a Coding binding")
    if coding_user_payload_digest(message) != binding.payload_digest:
        raise ValueError("RuntimeBinding payload digest does not match the message")
    evidence = require_json_mapping(
        {} if resource_metadata is None else dict(resource_metadata),
        name="Resume resource evidence metadata",
    )
    binding_metadata = binding.to_message_metadata()
    if evidence.keys() & binding_metadata.keys():
        raise ValueError("Resume metadata key conflict")
    record = AgentTranscriptRecordFactory(
        clock=lambda: created_at,
        id_factory=lambda: binding.record_id,
    ).create(
        AGENT_MESSAGE_KIND,
        message,
        parent_id=commit_parent_id,
        metadata={**evidence, **binding_metadata},
    )
    validate_coding_runtime_binding_record(
        record, expected_session_id=binding.session_id,
    )
    return record


def validate_coding_runtime_binding_record(
    record: AgentTranscriptRecord, *, expected_session_id: str,
) -> CodingRuntimeBindingV1:
    """Check the historical fact in one stored message, not live authority."""

    if record.kind != AGENT_MESSAGE_KIND or not isinstance(record.payload, UserMessage):
        raise ValueError("RuntimeBinding requires an agent UserMessage record")
    observation = inspect_coding_runtime_binding(record.metadata)
    binding = observation.binding
    if observation.status != "known" or binding is None:
        raise ValueError("RuntimeBinding metadata is absent or unsupported")
    if binding.record_id != record.record_id or binding.session_id != expected_session_id:
        raise ValueError("RuntimeBinding record or Session identity differs")
    if binding.payload_digest != coding_user_payload_digest(record.payload):
        raise ValueError("RuntimeBinding payload digest differs from the message")
    return binding


def _canonical_bytes(value: object) -> bytes:
    return dump_json_value(
        value, name="RuntimeBinding metadata", ensure_ascii=True, sort_keys=True,
    ).encode("utf-8")


def _require_identifier(value: object, *, name: str) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"RuntimeBinding {name} is invalid")


def _require_digest(value: object, *, name: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"RuntimeBinding {name} is invalid")


def _text(document: Mapping[str, object], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"RuntimeBinding {key} is invalid")
    return value


def _optional_text(document: Mapping[str, object], key: str) -> str | None:
    value = document[key]
    if value is None:
        return None
    return _text(document, key)


__all__ = [
    "CODING_RUNTIME_BINDING_MAX_BYTES",
    "CODING_RUNTIME_BINDING_METADATA_KEY",
    "CODING_RUNTIME_BINDING_VERSION",
    "CodingRuntimeBindingObservation",
    "CodingRuntimeBindingV1",
    "coding_user_input_digest",
    "freeze_coding_user_input",
    "coding_user_payload_digest",
    "inspect_coding_runtime_binding",
    "prepare_coding_resume_user_record",
    "validate_coding_runtime_binding_record",
]
