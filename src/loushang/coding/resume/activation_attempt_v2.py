"""Explicit Coding v2 intent facts; no admission or effect-settlement authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from loushang.coding.resume.activation_attempt import (
    _FIELDS,
    CodingActivationAttemptV1,
    _require_v1_budget,
)
from loushang.foundation.json import JSONValue
from loushang.harness.resume_effects import (
    ResumeEffectParentContextV1,
    _ResumeEffectOwnerFields,
)
from loushang.harness.transcript import _resume_records as _records
from loushang.harness.transcript.kinds import EXTENSION_DATA_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord, ExtensionData

CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE = "coding.activation-attempt/v2"
CODING_ACTIVATION_ATTEMPT_V2_MAX_BYTES = 8192
_INTENT_FIELDS = _FIELDS | {"effectOwners"}


_bytes = partial(_records.canonical_binding_bytes, name="Coding Resume intent v2")


@dataclass(frozen=True, slots=True)
class CodingResumeEffectOwnerV1(_ResumeEffectOwnerFields):
    """Frozen lookup obligations, validated again by the selected original owner."""

    owner_id: str
    scope_digest: str
    contract_digest: str
    phases: tuple[str, ...]
    effect_classes: tuple[str, ...] = ()
    _effect_owner_label = "Coding Resume"


@dataclass(frozen=True, slots=True)
class CodingActivationAttemptV2(CodingActivationAttemptV1):
    effect_owners: tuple[CodingResumeEffectOwnerV1, ...] = ()

    def __post_init__(self) -> None:
        CodingActivationAttemptV1._validate_v1_fields(self)
        _require_v1_budget(CodingActivationAttemptV1.to_data(self))
        owners = self.effect_owners
        if (
            type(owners) is not tuple
            or len(owners) > 8
            or any(type(owner) is not CodingResumeEffectOwnerV1 for owner in owners)
        ):
            raise ValueError("Coding Resume intent requires at most eight typed owners")
        identities = tuple(owner.identity for owner in owners)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("Coding Resume effect owners must be sorted and unique")
        if len(_bytes(self.to_data())) > CODING_ACTIVATION_ATTEMPT_V2_MAX_BYTES:
            raise ValueError("Coding Resume intent exceeds its 8 KiB byte budget")

    def to_data(self) -> dict[str, JSONValue]:
        document = CodingActivationAttemptV1.to_data(self)
        document["version"] = 2
        document["effectOwners"] = [owner.to_data() for owner in self.effect_owners]
        return document

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            b"loushang.coding.activation-attempt/v2\0" + _bytes(self.to_data())
        ).hexdigest()

    def parent_context(
        self, owner: CodingResumeEffectOwnerV1
    ) -> ResumeEffectParentContextV1:
        if (
            type(owner) is not CodingResumeEffectOwnerV1
            or owner not in self.effect_owners
        ):
            raise ValueError(
                "Coding Resume parent requires the exact frozen owner obligation"
            )
        return ResumeEffectParentContextV1(
            product_id="coding",
            session_id=self.session_id,
            attempt_id=self.attempt_id,
            request_id=self.request_id,
            intent_digest=self.digest,
            owner_id=owner.owner_id,
            scope_digest=owner.scope_digest,
            contract_digest=owner.contract_digest,
        )


def prepare_coding_activation_attempt_v2_record(
    attempt: CodingActivationAttemptV2,
    *,
    created_at: datetime,
) -> AgentTranscriptRecord:
    if type(attempt) is not CodingActivationAttemptV2:
        raise TypeError("Coding Resume v2 record requires an exact v2 intent")
    return _records.make_resume_record(
        EXTENSION_DATA_KIND,
        ExtensionData(CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE, attempt.to_data()),
        record_id=attempt.attempt_id,
        parent_id=attempt.original_leaf_id,
        created_at=created_at,
    )


def validate_coding_activation_attempt_v2_record(
    record: AgentTranscriptRecord,
) -> CodingActivationAttemptV2:
    if (
        record.kind != EXTENSION_DATA_KIND
        or type(record.payload) is not ExtensionData
        or record.payload.extension_type != CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE
    ):
        raise ValueError("Coding Resume v2 intent requires the exact extension record")
    raw = record.payload.data
    if type(raw) is not dict or set(raw) != _INTENT_FIELDS:
        raise ValueError("Coding Resume v2 intent fields are invalid")
    if type(raw["version"]) is not int or raw["version"] != 2:
        raise ValueError("Coding Resume v2 intent version is invalid")
    if type(raw["effectOwners"]) is not list or type(raw["effectClasses"]) is not list:
        raise ValueError("Coding Resume v2 intent lists are invalid")
    return _records.decode_attempt_record_fields(
        record,
        raw,
        effect_classes=tuple(raw["effectClasses"]),
        construct=partial(
            CodingActivationAttemptV2,
            effect_owners=tuple(
                CodingResumeEffectOwnerV1.from_data(owner) for owner in raw["effectOwners"]
            ),
        ),
        identity_error="Coding Resume v2 record identity or parent differs",
    )
