"""Explicit Coding v2 intent facts; no admission or effect-settlement authority."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from loushang.coding.resume_activation_attempt import CodingActivationAttemptV1
from loushang.foundation.json import JSONValue, dump_json_value
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.transcript.kinds import EXTENSION_DATA_KIND
from loushang.harness.transcript.types import AgentTranscriptRecord, ExtensionData
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE = "coding.activation-attempt/v2"
CODING_ACTIVATION_ATTEMPT_V2_MAX_BYTES = 8192
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_OWNER_FIELDS = {"ownerId", "scopeDigest", "contractDigest", "phases", "effectClasses"}
_INTENT_FIELDS = {
    "version",
    "attemptId",
    "requestId",
    "sessionId",
    "originalLeafId",
    "ancestryDigest",
    "planFingerprint",
    "epochFingerprint",
    "subjectDigest",
    "effectClasses",
    "effectOwners",
}


def _bytes(value: object) -> bytes:
    return dump_json_value(
        value,
        name="Coding Resume intent v2",
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _codes(value: tuple[str, ...], *, name: str, required: bool = False) -> None:
    if (
        type(value) is not tuple
        or len(value) > 16
        or (required and not value)
        or any(type(code) is not str or _CODE.fullmatch(code) is None for code in value)
        or value != tuple(sorted(set(value)))
    ):
        raise ValueError(f"Coding Resume {name} must be bounded, sorted and unique")


@dataclass(frozen=True, slots=True)
class CodingResumeEffectOwnerV1:
    """Frozen lookup obligations, validated again by the selected original owner."""

    owner_id: str
    scope_digest: str
    contract_digest: str
    phases: tuple[str, ...]
    effect_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.owner_id) is not str or _ID.fullmatch(self.owner_id) is None:
            raise ValueError("Coding Resume effect owner id is invalid")
        for value in (self.scope_digest, self.contract_digest):
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise ValueError("Coding Resume owner digest is invalid")
        _codes(self.phases, name="owner phases", required=True)
        _codes(self.effect_classes, name="owner effect classes")

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.owner_id, self.scope_digest, self.contract_digest

    def to_data(self) -> dict[str, JSONValue]:
        return {
            "ownerId": self.owner_id,
            "scopeDigest": self.scope_digest,
            "contractDigest": self.contract_digest,
            "phases": list(self.phases),
            "effectClasses": list(self.effect_classes),
        }

    @classmethod
    def from_data(cls, raw: object) -> CodingResumeEffectOwnerV1:
        if type(raw) is not dict or set(raw) != _OWNER_FIELDS:
            raise ValueError("Coding Resume effect owner fields are invalid")
        if type(raw["phases"]) is not list or type(raw["effectClasses"]) is not list:
            raise ValueError("Coding Resume owner codes require arrays")
        return cls(
            cast(str, raw["ownerId"]),
            cast(str, raw["scopeDigest"]),
            cast(str, raw["contractDigest"]),
            tuple(raw["phases"]),
            tuple(raw["effectClasses"]),
        )


@dataclass(frozen=True, slots=True)
class CodingActivationAttemptV2(CodingActivationAttemptV1):
    effect_owners: tuple[CodingResumeEffectOwnerV1, ...] = ()

    def __post_init__(self) -> None:
        # Validate the unchanged common fields through their explicit v1 value;
        # a v2 document is never relabelled as a v1 wire record.
        CodingActivationAttemptV1(
            self.attempt_id,
            self.request_id,
            self.session_id,
            self.original_leaf_id,
            self.ancestry_digest,
            self.plan_fingerprint,
            self.epoch_fingerprint,
            self.subject_digest,
            self.effect_classes,
        )
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
    return AgentTranscriptRecordFactory(
        clock=lambda: created_at, id_factory=lambda: attempt.attempt_id
    ).create(
        EXTENSION_DATA_KIND,
        ExtensionData(CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE, attempt.to_data()),
        parent_id=attempt.original_leaf_id,
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
    attempt = CodingActivationAttemptV2(
        attempt_id=cast(str, raw["attemptId"]),
        request_id=cast(str, raw["requestId"]),
        session_id=cast(str, raw["sessionId"]),
        original_leaf_id=cast(str | None, raw["originalLeafId"]),
        ancestry_digest=cast(str, raw["ancestryDigest"]),
        plan_fingerprint=cast(str, raw["planFingerprint"]),
        epoch_fingerprint=cast(str, raw["epochFingerprint"]),
        subject_digest=cast(str, raw["subjectDigest"]),
        effect_classes=tuple(cast(list[str], raw["effectClasses"])),
        effect_owners=tuple(
            CodingResumeEffectOwnerV1.from_data(owner) for owner in raw["effectOwners"]
        ),
    )
    if (
        record.record_id != attempt.attempt_id
        or record.parent_id != attempt.original_leaf_id
    ):
        raise ValueError("Coding Resume v2 record identity or parent differs")
    return attempt
