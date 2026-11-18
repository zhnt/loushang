"""Read-only payload value ports and original pure repair codecs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, Self, TypeVar, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_UNMARKED_DEPTH = 16
_MAX_UNMARKED_PATH_BYTES = 1024


class PayloadPlan(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def entrypoint(self) -> str: ...
    @property
    def payload_digest(self) -> str: ...
    @property
    def payload_size(self) -> int: ...
    @property
    def receipt_fingerprint(self) -> str: ...
    @property
    def stage_device(self) -> int: ...
    @property
    def stage_inode(self) -> int: ...


class EmptyPayloadPlan(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def stage_device(self) -> int: ...
    @property
    def stage_inode(self) -> int: ...


class PayloadMember(Protocol):
    @property
    def relative_path(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def device(self) -> int: ...
    @property
    def inode(self) -> int: ...
    @property
    def mode(self) -> int: ...
    @property
    def size(self) -> int: ...
    @property
    def digest(self) -> str | None: ...
    def to_dict(self) -> dict[str, object]: ...


class PayloadReview(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def stage_device(self) -> int: ...
    @property
    def stage_inode(self) -> int: ...
    @property
    def members(self) -> tuple[PayloadMember, ...]: ...


def plan_fields(plan: PayloadPlan) -> dict[str, object]:
    return {
        "attemptId": plan.attempt_id,
        "entrypoint": plan.entrypoint,
        "payloadDigest": plan.payload_digest,
        "payloadSize": plan.payload_size,
        "receiptFingerprint": plan.receipt_fingerprint,
        "stageDevice": plan.stage_device,
        "stageInode": plan.stage_inode,
        "version": 1,
    }


_PlanT = TypeVar("_PlanT", bound=PayloadPlan)


def plan_from_fields(
    plan_type: Callable[..., _PlanT], value: dict[str, object]
) -> _PlanT:
    """Construct only after the calling codec has checked its own envelope/version."""
    return plan_type(
        attempt_id=value["attemptId"],
        entrypoint=value["entrypoint"],
        payload_digest=value["payloadDigest"],
        payload_size=value["payloadSize"],
        receipt_fingerprint=value["receiptFingerprint"],
        stage_device=value["stageDevice"],
        stage_inode=value["stageInode"],
    )


def empty_fields(
    plan: EmptyPayloadPlan,
) -> dict[str, object]:
    return {
        "attemptId": plan.attempt_id,
        "stageDevice": plan.stage_device,
        "stageInode": plan.stage_inode,
        "version": 1,
    }


def complete_fields(
    plan: PayloadPlan, supervisor_fingerprint: str
) -> dict[str, object]:
    return {
        "plan": plan_fields(plan),
        "supervisorFingerprint": supervisor_fingerprint,
        "version": 1,
    }


def unmarked_fields(
    review: PayloadReview,
) -> dict[str, object]:
    return {
        "attemptId": review.attempt_id,
        "members": [member.to_dict() for member in review.members],
        "stageDevice": review.stage_device,
        "stageInode": review.stage_inode,
        "version": 1,
    }


@dataclass(frozen=True, slots=True)
class PayloadValueTypes:
    plan_type: Callable[..., PayloadPlan]
    empty_type: Callable[..., EmptyPayloadPlan]
    member_type: Callable[..., PayloadMember]
    review_type: Callable[..., PayloadReview]

    def decode_empty(self, body: bytes, attempt_id: str) -> EmptyPayloadPlan:
        value = json.loads(body)
        if (
            type(value) is not dict
            or set(value)
            != {
                "attemptId",
                "stageDevice",
                "stageInode",
                "version",
            }
            or value["version"] != 1
        ):
            raise ValueError("Worker empty repair record is invalid")
        plan = self.empty_type(
            attempt_id=value["attemptId"],
            stage_device=value["stageDevice"],
            stage_inode=value["stageInode"],
        )
        if (
            plan.attempt_id != attempt_id
            or body != canonical_json_bytes(empty_fields(plan)) + b"\n"
        ):
            raise ValueError("Worker empty repair record changed")
        return plan

    def decode_complete(self, body: bytes, attempt_id: str) -> tuple[PayloadPlan, str]:
        value = json.loads(body)
        if (
            type(value) is not dict
            or set(value) != {"plan", "supervisorFingerprint", "version"}
            or value["version"] != 1
            or type(value["plan"]) is not dict
            or set(value["plan"])
            != {
                "attemptId",
                "entrypoint",
                "payloadDigest",
                "payloadSize",
                "receiptFingerprint",
                "stageDevice",
                "stageInode",
                "version",
            }
        ):
            raise ValueError("Worker complete repair record is invalid")
        raw_plan = value["plan"]
        plan = plan_from_fields(self.plan_type, raw_plan)
        supervisor_fingerprint = value["supervisorFingerprint"]
        if (
            raw_plan["version"] != 1
            or plan.attempt_id != attempt_id
            or not isinstance(supervisor_fingerprint, str)
            or _DIGEST.fullmatch(supervisor_fingerprint) is None
            or body
            != canonical_json_bytes(complete_fields(plan, supervisor_fingerprint))
            + b"\n"
        ):
            raise ValueError("Worker complete repair record changed")
        return plan, supervisor_fingerprint

    def decode_unmarked(self, body: bytes, attempt_id: str) -> PayloadReview:
        value = json.loads(body)
        if (
            type(value) is not dict
            or set(value)
            != {"attemptId", "members", "stageDevice", "stageInode", "version"}
            or value["version"] != 1
            or type(value["members"]) is not list
            or not 1 <= len(value["members"]) <= _MAX_UNMARKED_DEPTH + 1
        ):
            raise ValueError("Worker unmarked repair record is invalid")
        members: list[PayloadMember] = []
        for raw in value["members"]:
            if type(raw) is not dict or set(raw) != {
                "device",
                "digest",
                "inode",
                "kind",
                "mode",
                "relativePath",
                "size",
            }:
                raise ValueError("Worker unmarked repair member is invalid")
            members.append(
                self.member_type(
                    relative_path=raw["relativePath"],
                    kind=raw["kind"],
                    device=raw["device"],
                    inode=raw["inode"],
                    mode=raw["mode"],
                    size=raw["size"],
                    digest=raw["digest"],
                )
            )
        review = self.review_type(
            attempt_id=value["attemptId"],
            stage_device=value["stageDevice"],
            stage_inode=value["stageInode"],
            members=tuple(members),
        )
        if (
            review.attempt_id != attempt_id
            or body != canonical_json_bytes(unmarked_fields(review)) + b"\n"
        ):
            raise ValueError("Worker unmarked repair record changed")
        return review


class PayloadPlanMethods:
    __slots__ = ()
    _invalid_message: str

    def __post_init__(self) -> None:
        facts = cast(PayloadPlan, self)
        if (
            _ATTEMPT.fullmatch(facts.attempt_id) is None
            or canonical_plugin_relative_path(facts.entrypoint).as_posix()
            != facts.entrypoint
            or _DIGEST.fullmatch(facts.payload_digest) is None
            or (_DIGEST.fullmatch(facts.receipt_fingerprint) is None)
            or (type(facts.payload_size) is not int)
            or (not 0 < facts.payload_size <= 16 * 1024 * 1024)
            or (type(facts.stage_device) is not int)
            or (facts.stage_device < 0)
            or (type(facts.stage_inode) is not int)
            or (facts.stage_inode < 1)
        ):
            raise ValueError(self._invalid_message)

    @property
    def fingerprint(self) -> str:
        facts = cast(PayloadPlan, self)
        return sha256(canonical_json_bytes(plan_fields(facts))).hexdigest()


class EmptyPayloadPlanMethods:
    __slots__ = ()
    _invalid_message: str

    def __post_init__(self) -> None:
        facts = cast(EmptyPayloadPlan, self)
        if (
            _ATTEMPT.fullmatch(facts.attempt_id) is None
            or type(facts.stage_device) is not int
            or facts.stage_device < 0
            or (type(facts.stage_inode) is not int)
            or (facts.stage_inode < 1)
        ):
            raise ValueError(self._invalid_message)

    @property
    def fingerprint(self) -> str:
        facts = cast(EmptyPayloadPlan, self)
        return sha256(canonical_json_bytes(empty_fields(facts))).hexdigest()


class PayloadMemberMethods:
    __slots__ = ()
    _invalid_message: str

    def __post_init__(self) -> None:
        facts = cast(PayloadMember, self)
        if (
            not isinstance(facts.relative_path, str)
            or canonical_plugin_relative_path(facts.relative_path).as_posix()
            != facts.relative_path
            or facts.kind not in {"directory", "file"}
            or (type(facts.device) is not int)
            or (facts.device < 0)
            or (type(facts.inode) is not int)
            or (facts.inode < 1)
            or (type(facts.mode) is not int)
            or (type(facts.size) is not int)
            or (facts.size < 0)
            or (
                facts.kind == "directory"
                and (facts.mode != 448 or facts.size != 0 or facts.digest is not None)
            )
            or (
                facts.kind == "file"
                and (
                    facts.mode not in {384, 320}
                    or facts.size > 16 * 1024 * 1024
                    or (not isinstance(facts.digest, str))
                    or (_DIGEST.fullmatch(facts.digest) is None)
                )
            )
        ):
            raise ValueError(self._invalid_message)

    def to_dict(self) -> dict[str, object]:
        facts = cast(PayloadMember, self)
        return {
            "device": facts.device,
            "digest": facts.digest,
            "inode": facts.inode,
            "kind": facts.kind,
            "mode": facts.mode,
            "relativePath": facts.relative_path,
            "size": facts.size,
        }


class PayloadReviewMethods:
    __slots__ = ()
    _invalid_message: str
    _invalid_member_message: str
    _chain_changed_message: str
    _member_type: type[PayloadMember]
    _maximum_depth: Callable[[], int]
    _maximum_path_bytes: Callable[[], int]

    def __post_init__(self) -> None:
        facts = cast(PayloadReview, self)
        if (
            not isinstance(facts.attempt_id, str)
            or _ATTEMPT.fullmatch(facts.attempt_id) is None
            or type(facts.stage_device) is not int
            or (facts.stage_device < 0)
            or (type(facts.stage_inode) is not int)
            or (facts.stage_inode < 1)
            or (not isinstance(facts.members, tuple))
            or (not 1 <= len(facts.members) <= self._maximum_depth() + 1)
        ):
            raise ValueError(self._invalid_message)
        parent = ""
        for index, member in enumerate(facts.members):
            if not isinstance(member, self._member_type):
                raise ValueError(self._invalid_member_message)
            parts = canonical_plugin_relative_path(member.relative_path).parts
            if (
                len(parts) != index + 1
                or (parent and (not member.relative_path.startswith(parent + "/")))
                or (member.kind == "file" and index != len(facts.members) - 1)
                or (len(os.fsencode(member.relative_path)) > self._maximum_path_bytes())
            ):
                raise ValueError(self._chain_changed_message)
            parent = member.relative_path

    @property
    def fingerprint(self) -> str:
        facts = cast(PayloadReview, self)
        return sha256(canonical_json_bytes(unmarked_fields(facts))).hexdigest()


class RegisteredPayloadRepairIntentMethods:
    __slots__ = ()
    _plan_type: type[PayloadPlan]
    plan: PayloadPlan
    gate_record_digest: str
    receipt_record_digest: str
    policy_fingerprint: str
    lease_id: str
    host_identity: str
    boot_identity: str
    owner_generation: int

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not self._plan_type
            or any(
                (
                    type(value) is not str or _DIGEST.fullmatch(value) is None
                    for value in (
                        self.gate_record_digest,
                        self.receipt_record_digest,
                        self.policy_fingerprint,
                        self.lease_id,
                    )
                )
            )
            or type(self.host_identity) is not str
            or (not self.host_identity)
            or (type(self.boot_identity) is not str)
            or (not self.boot_identity)
            or (type(self.owner_generation) is not int)
            or (self.owner_generation < 0)
        ):
            raise ValueError("Registered Worker payload repair intent is invalid")

    @property
    def attempt_id(self) -> str:
        return self.plan.attempt_id

    def to_dict(self) -> dict[str, object]:
        return {
            "bootIdentity": self.boot_identity,
            "gateRecordDigest": self.gate_record_digest,
            "hostIdentity": self.host_identity,
            "leaseId": self.lease_id,
            "ownerGeneration": self.owner_generation,
            "plan": plan_fields(self.plan),
            "policyFingerprint": self.policy_fingerprint,
            "receiptRecordDigest": self.receipt_record_digest,
            "version": 1,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if (
            type(value) is not dict
            or set(value)
            != {
                "bootIdentity",
                "gateRecordDigest",
                "hostIdentity",
                "leaseId",
                "ownerGeneration",
                "plan",
                "policyFingerprint",
                "receiptRecordDigest",
                "version",
            }
            or value["version"] != 1
        ):
            raise ValueError("Registered Worker payload repair fields are invalid")
        raw_plan = value["plan"]
        if (
            type(raw_plan) is not dict
            or set(raw_plan)
            != {
                "attemptId",
                "entrypoint",
                "payloadDigest",
                "payloadSize",
                "receiptFingerprint",
                "stageDevice",
                "stageInode",
                "version",
            }
            or raw_plan["version"] != 1
        ):
            raise ValueError("Registered Worker payload repair plan is invalid")
        return cast(Callable[..., Self], cls)(
            plan=plan_from_fields(cls._plan_type, raw_plan),
            gate_record_digest=value["gateRecordDigest"],
            receipt_record_digest=value["receiptRecordDigest"],
            policy_fingerprint=value["policyFingerprint"],
            lease_id=value["leaseId"],
            host_identity=value["hostIdentity"],
            boot_identity=value["bootIdentity"],
            owner_generation=value["ownerGeneration"],
        )

    @classmethod
    def from_repair_record(cls, body: bytes, attempt_id: str) -> Self:
        intent = cls.from_dict(json.loads(body))
        if (
            intent.attempt_id != attempt_id
            or body != canonical_json_bytes(intent.to_dict()) + b"\n"
        ):
            raise ValueError("Registered Worker payload repair changed")
        return intent
