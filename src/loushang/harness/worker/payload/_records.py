"""Read-only payload value ports and original pure repair codecs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

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
        plan = self.plan_type(
            attempt_id=raw_plan["attemptId"],
            entrypoint=raw_plan["entrypoint"],
            payload_digest=raw_plan["payloadDigest"],
            payload_size=raw_plan["payloadSize"],
            receipt_fingerprint=raw_plan["receiptFingerprint"],
            stage_device=raw_plan["stageDevice"],
            stage_inode=raw_plan["stageInode"],
        )
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
