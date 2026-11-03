"""Coding-owned, inert activation attempt fact for a resumed user input.

An attempt records the activation selected by its owner. It is neither
current authority nor evidence that an effect or user input completed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from loushang.ai.types import UserMessage
from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND, EXTENSION_DATA_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord, ExtensionData
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

from .resume_binding import (
    inspect_coding_runtime_binding,
    validate_coding_runtime_binding_record,
)

CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE = "coding.activation-attempt/v1"
CODING_ACTIVATION_ATTEMPT_MAX_BYTES = 4096

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_EFFECT_CODE = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_FIELDS = frozenset({
    "version", "attemptId", "requestId", "sessionId", "originalLeafId",
    "ancestryDigest", "planFingerprint", "epochFingerprint", "subjectDigest",
    "effectClasses",
})


@dataclass(frozen=True, slots=True)
class CodingActivationAttemptV1:
    """Bounded historical intent, without approval or effect-settlement meaning."""

    attempt_id: str
    request_id: str
    session_id: str
    original_leaf_id: str | None
    ancestry_digest: str
    plan_fingerprint: str
    epoch_fingerprint: str
    subject_digest: str
    effect_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("attempt_id", "request_id", "session_id"):
            value = getattr(self, name)
            if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"activation attempt {name} is invalid")
        if self.original_leaf_id is not None and (
            type(self.original_leaf_id) is not str
            or _IDENTIFIER.fullmatch(self.original_leaf_id) is None
        ):
            raise ValueError("activation attempt original leaf is invalid")
        for name in (
            "ancestry_digest", "plan_fingerprint", "epoch_fingerprint",
            "subject_digest",
        ):
            value = getattr(self, name)
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise ValueError(f"activation attempt {name} is invalid")
        codes = self.effect_classes
        if (
            type(codes) is not tuple or len(codes) > 16
            or any(type(code) is not str or _EFFECT_CODE.fullmatch(code) is None
                   for code in codes)
            or codes != tuple(sorted(set(codes)))
        ):
            raise ValueError("activation attempt effect classes are invalid")
        if len(_encoded(self.to_data())) > CODING_ACTIVATION_ATTEMPT_MAX_BYTES:
            raise ValueError("activation attempt exceeds its byte budget")

    def to_data(self) -> dict[str, JSONValue]:
        return {
            "version": 1,
            "attemptId": self.attempt_id,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "originalLeafId": self.original_leaf_id,
            "ancestryDigest": self.ancestry_digest,
            "planFingerprint": self.plan_fingerprint,
            "epochFingerprint": self.epoch_fingerprint,
            "subjectDigest": self.subject_digest,
            "effectClasses": list(self.effect_classes),
        }


@dataclass(frozen=True, slots=True)
class CodingActivationAttemptPathProjection:
    """Selected-path attempt state; absence is not a durable lookup receipt."""

    status: Literal["none", "pending", "unknown_version"]
    attempt: CodingActivationAttemptV1 | None = None
    record_id: str | None = None


class CodingResumeRecoveryRequired(RuntimeError):
    """An ordinary writable route reached unresolved historical activation."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"Coding Resume recovery required: {reason_code}")


def require_no_unsettled_coding_activation(
    records: Iterable[AgentTranscriptRecord], *, current_session_id: str,
) -> None:
    """Fence ordinary writes while an activation attempt needs reconciliation."""

    try:
        projection = project_coding_activation_attempt_path(
            records, current_session_id=current_session_id,
        )
    except ValueError as error:
        raise CodingResumeRecoveryRequired("history.activation_invalid") from error
    if projection.status != "none":
        raise CodingResumeRecoveryRequired(f"history.activation_{projection.status}")


def project_coding_activation_attempt_path(
    records: Iterable[AgentTranscriptRecord], *, current_session_id: str,
) -> CodingActivationAttemptPathProjection:
    """Detect an unbound attempt without interpreting it as settled authority.

    The caller supplies a complete selected root-to-leaf path. A source Session
    attempt copied by a fork remains historical origin, not target pending work.
    Any unknown attempt version on the path conservatively blocks planning.
    """

    if type(current_session_id) is not str or _IDENTIFIER.fullmatch(current_session_id) is None:
        raise ValueError("activation attempt current Session id is invalid")
    ancestry = hashlib.sha256(b"loushang.coding.resume-ancestry/v1\0")
    previous_id: str | None = None
    seen: set[str] = set()
    pending: CodingActivationAttemptV1 | None = None
    pending_record_id: str | None = None
    unknown_version = False
    for record in records:
        if record.parent_id != previous_id or record.record_id in seen:
            raise ValueError("activation attempt projection requires a complete path")
        seen.add(record.record_id)
        prefix_digest = ancestry.hexdigest()
        payload = record.payload
        if isinstance(payload, ExtensionData) and payload.extension_type.startswith(
            "coding.activation-attempt/"
        ):
            if payload.extension_type != CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE:
                unknown_version = True
            else:
                attempt = validate_coding_activation_attempt_record(record)
                if attempt.ancestry_digest != prefix_digest:
                    raise ValueError("activation attempt ancestry does not match history")
                if attempt.session_id == current_session_id:
                    if pending is not None:
                        raise ValueError("activation attempt precedes unresolved intent")
                    pending = attempt
                    pending_record_id = record.record_id
        observation = inspect_coding_runtime_binding(record.metadata)
        if observation.status != "absent":
            if record.kind != AGENT_MESSAGE_KIND or not isinstance(
                record.payload, UserMessage,
            ):
                raise ValueError("activation Binding requires a user message")
            if observation.status == "unknown_version":
                unknown_version = True
            else:
                observed_binding = observation.binding
                if observed_binding is None:
                    raise ValueError("activation Binding known schema is missing")
                binding = validate_coding_runtime_binding_record(
                    record, expected_session_id=observed_binding.session_id,
                )
                if binding.session_id == current_session_id and pending is not None:
                    if (
                        record.parent_id != pending_record_id
                        or binding.attempt_id != pending.attempt_id
                        or binding.input_id != pending.request_id
                        or binding.original_leaf_id != pending.original_leaf_id
                        or binding.ancestry_digest != pending.ancestry_digest
                        or binding.planned_fingerprint != pending.plan_fingerprint
                        or binding.actual_fingerprint != pending.epoch_fingerprint
                        or binding.subject_digest != pending.subject_digest
                    ):
                        raise ValueError("activation Binding does not match intent")
                    pending = None
                    pending_record_id = None
        identity = _encoded({
            "recordId": record.record_id, "parentId": record.parent_id,
        })
        ancestry.update(len(identity).to_bytes(4, "big"))
        ancestry.update(identity)
        previous_id = record.record_id
    if unknown_version:
        return CodingActivationAttemptPathProjection("unknown_version")
    if pending is not None:
        return CodingActivationAttemptPathProjection(
            "pending", attempt=pending, record_id=pending_record_id,
        )
    return CodingActivationAttemptPathProjection("none")


def prepare_coding_activation_attempt_record(
    attempt: CodingActivationAttemptV1, *, created_at: datetime,
) -> AgentTranscriptRecord:
    """Build a fixed-ID intent after admission; committing belongs to Transcript."""

    if not isinstance(attempt, CodingActivationAttemptV1):
        raise TypeError("activation attempt record requires a Coding attempt")
    record = AgentTranscriptRecordFactory(
        clock=lambda: created_at,
        id_factory=lambda: attempt.attempt_id,
    ).create(
        EXTENSION_DATA_KIND,
        ExtensionData(CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE, attempt.to_data()),
        parent_id=attempt.original_leaf_id,
    )
    validate_coding_activation_attempt_record(record)
    return record


def validate_coding_activation_attempt_record(
    record: AgentTranscriptRecord,
) -> CodingActivationAttemptV1:
    """Decode an exact v1 selected-path fact; reject unknown or malformed intent."""

    if record.kind != EXTENSION_DATA_KIND or not isinstance(record.payload, ExtensionData):
        raise ValueError("activation attempt requires an extension data record")
    payload = record.payload
    if payload.extension_type != CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE:
        raise ValueError("activation attempt extension type is invalid")
    raw = payload.data
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise ValueError("activation attempt fields are invalid")
    data = require_json_mapping(raw, name="activation attempt")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("activation attempt version is invalid")
    effects = data["effectClasses"]
    if not isinstance(effects, list):
        raise ValueError("activation attempt effect classes are invalid")
    attempt = CodingActivationAttemptV1(
        attempt_id=cast(str, data["attemptId"]),
        request_id=cast(str, data["requestId"]),
        session_id=cast(str, data["sessionId"]),
        original_leaf_id=cast(str | None, data["originalLeafId"]),
        ancestry_digest=cast(str, data["ancestryDigest"]),
        plan_fingerprint=cast(str, data["planFingerprint"]),
        epoch_fingerprint=cast(str, data["epochFingerprint"]),
        subject_digest=cast(str, data["subjectDigest"]),
        effect_classes=cast(tuple[str, ...], tuple(effects)),
    )
    if record.record_id != attempt.attempt_id or record.parent_id != attempt.original_leaf_id:
        raise ValueError("activation attempt record identity or parent differs")
    return attempt


def _encoded(value: object) -> bytes:
    return dump_json_value(
        value, name="activation attempt", ensure_ascii=True, sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE",
    "CODING_ACTIVATION_ATTEMPT_MAX_BYTES",
    "CodingActivationAttemptPathProjection",
    "CodingActivationAttemptV1",
    "CodingResumeRecoveryRequired",
    "prepare_coding_activation_attempt_record",
    "project_coding_activation_attempt_path",
    "require_no_unsettled_coding_activation",
    "validate_coding_activation_attempt_record",
]
