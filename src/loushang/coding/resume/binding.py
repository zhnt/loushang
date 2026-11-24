"""Coding-owned historical RuntimeBinding metadata for one resumed user input.

This value records what an activation selected. It does not grant present
authority, prove effect settlement, or admit a Model or Tool invocation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Literal

from loushang.ai.types import UserMessage
from loushang.coding.composition.provenance import CodingCompositionProvenanceV1
from loushang.foundation.json import JSONValue
from loushang.harness.transcript import _resume_records as _records
from loushang.harness.transcript._resume_records import SelectedAncestry
from loushang.harness.transcript.types import AgentTranscriptRecord

if TYPE_CHECKING:
    from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1


CODING_RUNTIME_BINDING_METADATA_KEY = "coding.runtimeBindingV1"
CODING_RUNTIME_BINDING_VERSION = 1
CODING_RUNTIME_BINDING_MAX_BYTES = 4096

_ANCESTRY_DOMAIN = b"loushang.coding.resume-ancestry/v1\0"
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
        self._validate_v1_fields()
        _require_v1_budget(self._document())

    def _validate_v1_fields(self) -> None:
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
    return _records.project_legacy_runtime_binding(
        records,
        current_session_id=current_session_id,
        ancestry=SelectedAncestry(_ANCESTRY_DOMAIN),
        inspect_binding=inspect_coding_runtime_binding,
        digest=coding_user_payload_digest,
        construct=CodingRuntimeBindingPathProjection,
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
    return CodingRuntimeBindingObservation("known", _decode_runtime_binding_fields(raw))


def _decode_runtime_binding_fields(raw: Mapping[str, object]) -> CodingRuntimeBindingV1:
    if set(raw) != _FIELDS:
        raise ValueError("RuntimeBinding metadata fields are invalid")
    return _records.decode_resume_binding_document(
        raw, construct=CodingRuntimeBindingV1, construct_origin=CodingCompositionProvenanceV1
    )


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


def freeze_coding_user_input(message: UserMessage) -> UserMessage:
    """Detach mutable caller content using the original Transcript codec."""

    return _records.freeze_user_message(message)


def coding_user_input_digest(message: UserMessage) -> str:
    """Freeze admitted input bytes before image externalization, without writes."""
    return _records.user_message_digest(
        message,
        digest_domain=b"loushang.coding.resume-input/v1\0",
        require_externalized_images=False,
    )


def coding_user_payload_digest(message: UserMessage) -> str:
    """Digest the exact persisted UserMessage payload, including image refs."""
    return _records.user_message_digest(
        message,
        digest_domain=b"loushang.coding.resume-user-message/v1\0",
        require_externalized_images=True,
    )


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
    return _records.make_resume_user_record(
        message,
        binding,
        parent_id=commit_parent_id,
        created_at=created_at,
        resource_metadata=resource_metadata,
        evidence_name="Resume resource evidence metadata",
        metadata_conflict="Resume metadata key conflict",
        digest=coding_user_payload_digest,
        payload_error="RuntimeBinding payload digest does not match the message",
        validate=lambda record: validate_coding_runtime_binding_record(
            record, expected_session_id=binding.session_id
        ),
    )


def validate_coding_runtime_binding_record(
    record: AgentTranscriptRecord, *, expected_session_id: str,
) -> CodingRuntimeBindingV1:
    """Check the historical fact in one stored message, not live authority."""

    payload = _require_v1_user_payload(record)
    observation = inspect_coding_runtime_binding(record.metadata)
    binding = observation.binding
    if observation.status != "known" or binding is None:
        raise ValueError("RuntimeBinding metadata is absent or unsupported")
    _require_decoded_v1_binding(
        record, binding, payload=payload, expected_session_id=expected_session_id,
    )
    return binding


_require_v1_user_payload = _records.require_legacy_resume_user_payload
_require_decoded_v1_binding = partial(
    _records.require_legacy_resume_binding, digest=coding_user_payload_digest
)


_canonical_bytes = _records.canonical_binding_bytes


def _require_v1_budget(document: object) -> None:
    if len(_canonical_bytes(document)) > CODING_RUNTIME_BINDING_MAX_BYTES:
        raise ValueError("RuntimeBinding metadata exceeds its byte budget")


def _require_identifier(value: object, *, name: str) -> None:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"RuntimeBinding {name} is invalid")


def _require_digest(value: object, *, name: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"RuntimeBinding {name} is invalid")


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
