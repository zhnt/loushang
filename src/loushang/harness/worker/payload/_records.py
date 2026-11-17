"""Read-only payload value ports and original pure repair codecs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

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


class PayloadPlanMethods:
    __slots__ = ()
    _invalid_message: str
    attempt_id: str
    entrypoint: str
    payload_digest: str
    payload_size: int
    receipt_fingerprint: str
    stage_device: int
    stage_inode: int

    def __post_init__(self) -> None:
        if (
            _ATTEMPT.fullmatch(self.attempt_id) is None
            or canonical_plugin_relative_path(self.entrypoint).as_posix()
            != self.entrypoint
            or _DIGEST.fullmatch(self.payload_digest) is None
            or (_DIGEST.fullmatch(self.receipt_fingerprint) is None)
            or (type(self.payload_size) is not int)
            or (not 0 < self.payload_size <= 16 * 1024 * 1024)
            or (type(self.stage_device) is not int)
            or (self.stage_device < 0)
            or (type(self.stage_inode) is not int)
            or (self.stage_inode < 1)
        ):
            raise ValueError(self._invalid_message)

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(plan_fields(self))).hexdigest()


class EmptyPayloadPlanMethods:
    __slots__ = ()
    _invalid_message: str
    attempt_id: str
    stage_device: int
    stage_inode: int

    def __post_init__(self) -> None:
        if (
            _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_device) is not int
            or self.stage_device < 0
            or (type(self.stage_inode) is not int)
            or (self.stage_inode < 1)
        ):
            raise ValueError(self._invalid_message)

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(empty_fields(self))).hexdigest()


class PayloadMemberMethods:
    __slots__ = ()
    _invalid_message: str
    relative_path: str
    kind: str
    device: int
    inode: int
    mode: int
    size: int
    digest: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative_path, str)
            or canonical_plugin_relative_path(self.relative_path).as_posix()
            != self.relative_path
            or self.kind not in {"directory", "file"}
            or (type(self.device) is not int)
            or (self.device < 0)
            or (type(self.inode) is not int)
            or (self.inode < 1)
            or (type(self.mode) is not int)
            or (type(self.size) is not int)
            or (self.size < 0)
            or (
                self.kind == "directory"
                and (self.mode != 448 or self.size != 0 or self.digest is not None)
            )
            or (
                self.kind == "file"
                and (
                    self.mode not in {384, 320}
                    or self.size > 16 * 1024 * 1024
                    or (not isinstance(self.digest, str))
                    or (_DIGEST.fullmatch(self.digest) is None)
                )
            )
        ):
            raise ValueError(self._invalid_message)

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "digest": self.digest,
            "inode": self.inode,
            "kind": self.kind,
            "mode": self.mode,
            "relativePath": self.relative_path,
            "size": self.size,
        }


class PayloadReviewMethods:
    __slots__ = ()
    _invalid_message: str
    _invalid_member_message: str
    _chain_changed_message: str
    _member_type: type[PayloadMember]
    _maximum_depth: Callable[[], int]
    _maximum_path_bytes: Callable[[], int]
    attempt_id: str
    stage_device: int
    stage_inode: int
    members: tuple[PayloadMember, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_device) is not int
            or (self.stage_device < 0)
            or (type(self.stage_inode) is not int)
            or (self.stage_inode < 1)
            or (not isinstance(self.members, tuple))
            or (not 1 <= len(self.members) <= self._maximum_depth() + 1)
        ):
            raise ValueError(self._invalid_message)
        parent = ""
        for index, member in enumerate(self.members):
            if not isinstance(member, self._member_type):
                raise ValueError(self._invalid_member_message)
            parts = canonical_plugin_relative_path(member.relative_path).parts
            if (
                len(parts) != index + 1
                or (parent and (not member.relative_path.startswith(parent + "/")))
                or (member.kind == "file" and index != len(self.members) - 1)
                or (len(os.fsencode(member.relative_path)) > self._maximum_path_bytes())
            ):
                raise ValueError(self._chain_changed_message)
            parent = member.relative_path

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(unmarked_fields(self))).hexdigest()
