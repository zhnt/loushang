"""Coding-owned, inert activation attempt fact for a resumed user input.

An attempt records the activation selected by its owner. It is neither
current authority nor evidence that an effect or user input completed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Literal

from loushang.coding.resume.binding import (
    _ANCESTRY_DOMAIN,
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    inspect_coding_runtime_binding,
    matches_intent,
)
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.resume_effects import (
    is_resume_digest,
    is_resume_identifier,
    valid_resume_effect_codes,
)
from loushang.harness.transcript import _resume_records as _records
from loushang.harness.transcript._resume_records import SelectedAncestry
from loushang.harness.transcript.kinds import EXTENSION_DATA_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord, ExtensionData

CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE = "coding.activation-attempt/v1"
CODING_ACTIVATION_ATTEMPT_MAX_BYTES = 4096

_FIELDS = _records.ACTIVATION_ATTEMPT_FIELDS


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
        self._validate_v1_fields()
        _require_v1_budget(self.to_data())

    def _validate_v1_fields(self) -> None:
        for name in ("attempt_id", "request_id", "session_id"):
            value = getattr(self, name)
            if not is_resume_identifier(value):
                raise ValueError(f"activation attempt {name} is invalid")
        if self.original_leaf_id is not None and not is_resume_identifier(self.original_leaf_id):
            raise ValueError("activation attempt original leaf is invalid")
        for name in (
            "ancestry_digest", "plan_fingerprint", "epoch_fingerprint",
            "subject_digest",
        ):
            value = getattr(self, name)
            if not is_resume_digest(value):
                raise ValueError(f"activation attempt {name} is invalid")
        if not valid_resume_effect_codes(self.effect_classes):
            raise ValueError("activation attempt effect classes are invalid")

    def to_data(self) -> dict[str, JSONValue]:
        return _records.encode_attempt_document(self)


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

    if not is_resume_identifier(current_session_id):
        raise ValueError("activation attempt current Session id is invalid")
    result = _records.finish_history_scan(_records.scan_activation_history(
        records,
        current_session_id=current_session_id,
        ancestry=SelectedAncestry(_ANCESTRY_DOMAIN),
        encode=_encoded,
        attempt_prefix="coding.activation-attempt/",
        attempt_readers={
            CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE: validate_coding_activation_attempt_record,
        },
        read_binding=_read_legacy_attempt_binding,
        path_error="activation attempt projection requires a complete path",
        ancestry_error="activation attempt ancestry does not match history",
        duplicate_error="activation attempt precedes unresolved intent",
        track_other_sessions=False,
    ))
    attempt = result.attempt
    return CodingActivationAttemptPathProjection(
        result.status, attempt=attempt, record_id=None if attempt is None else attempt.attempt_id,
    )


def _read_legacy_attempt_binding(
    record: AgentTranscriptRecord, pending: Mapping[str, CodingActivationAttemptV1],
) -> CodingRuntimeBindingV1 | Literal["unknown_version"] | None:
    binding = _records.read_legacy_runtime_binding(
        record,
        inspect_binding=inspect_coding_runtime_binding,
        digest=coding_user_payload_digest,
        payload_error="activation Binding requires a user message",
        missing_error="activation Binding known schema is missing",
    )
    if binding is None or isinstance(binding, str):
        return binding
    attempt = pending.get(binding.session_id)
    if attempt is not None and (
        record.parent_id != attempt.attempt_id
        or not matches_intent(binding, attempt, check_session=False)
    ):
        raise ValueError("activation Binding does not match intent")
    return binding


def prepare_coding_activation_attempt_record(
    attempt: CodingActivationAttemptV1, *, created_at: datetime,
) -> AgentTranscriptRecord:
    """Build a fixed-ID intent after admission; committing belongs to Transcript."""

    if not isinstance(attempt, CodingActivationAttemptV1):
        raise TypeError("activation attempt record requires a Coding attempt")
    record = _records.make_resume_record(
        EXTENSION_DATA_KIND,
        ExtensionData(CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE, attempt.to_data()),
        record_id=attempt.attempt_id,
        parent_id=attempt.original_leaf_id,
        created_at=created_at,
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
    return _records.decode_attempt_record_fields(
        record,
        data,
        effect_classes=tuple(effects),
        construct=CodingActivationAttemptV1,
        identity_error="activation attempt record identity or parent differs",
    )


_encoded = partial(_records.canonical_binding_bytes, name="activation attempt")


def _require_v1_budget(document: object) -> None:
    if len(_encoded(document)) > CODING_ACTIVATION_ATTEMPT_MAX_BYTES:
        raise ValueError("activation attempt exceeds its byte budget")


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
