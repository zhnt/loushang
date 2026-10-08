"""Offline, read-only review of a cleanly stopped Windows Worker payload.

This captures exact retained bytes and identities for a later retirement
transaction. It does not claim that deletion, Job recovery, or rotation has
occurred, and it grants no filesystem mutation authority by itself.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from hashlib import sha256

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)

from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _read_intent_under_gc_guard,
)
from .package_product_worker_windows_payload import _marker_bytes
from .package_product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MARKER = "worker-payload.json"
_MAX_MARKER_BYTES = 1024
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_REVIEW_BYTES = 32768
_READ_CHUNK = 1024 * 1024
_DIRECTORY_ATTRIBUTES = 0x00000010 | 0x00000020 | 0x00002000
_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000

FileIdentity = tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _CapturedStageBytesV1:
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str


class CodingWindowsWorkerStageReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageReviewV1:
    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    supervisor_revision: int
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except ValueError as exc:
            raise ValueError(
                "Windows Worker stage review entrypoint is invalid"
            ) from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (self.intent_fingerprint, self.executable_digest)
            )
            or any(
                type(value) is not int or value < 1
                for value in (
                    self.lease_owner_revision,
                    self.native_revision,
                    self.supervisor_revision,
                )
            )
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or self.executable_identity[3] < 1
            or self.executable_identity[3] > _MAX_PAYLOAD_BYTES
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(item[1])
                for index, item in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker stage review is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "directoryIdentities": [
                [path, list(identity)] for path, identity in self.directory_identities
            ],
            "entrypoint": self.entrypoint,
            "executableDigest": self.executable_digest,
            "executableIdentity": list(self.executable_identity),
            "intentFingerprint": self.intent_fingerprint,
            "leaseOwnerRevision": self.lease_owner_revision,
            "markerIdentity": list(self.marker_identity),
            "nativeRevision": self.native_revision,
            "stageIdentity": list(self.stage_identity),
            "supervisorRevision": self.supervisor_revision,
            "version": 1,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerStageReviewV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_REVIEW_BYTES:
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_record_invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptId",
                    "directoryIdentities",
                    "entrypoint",
                    "executableDigest",
                    "executableIdentity",
                    "intentFingerprint",
                    "leaseOwnerRevision",
                    "markerIdentity",
                    "nativeRevision",
                    "stageIdentity",
                    "supervisorRevision",
                    "version",
                }
                or value["version"] != 1
            ):
                raise ValueError("Windows Worker stage review fields changed")
            directories = value["directoryIdentities"]
            if type(directories) is not list or any(
                type(item) is not list or len(item) != 2 or type(item[1]) is not list
                for item in directories
            ):
                raise ValueError("Windows Worker stage review directories changed")
            for name in ("stageIdentity", "markerIdentity", "executableIdentity"):
                if type(value[name]) is not list:
                    raise ValueError("Windows Worker stage review identity changed")
            review = cls(
                attempt_id=value["attemptId"],
                intent_fingerprint=value["intentFingerprint"],
                lease_owner_revision=value["leaseOwnerRevision"],
                native_revision=value["nativeRevision"],
                supervisor_revision=value["supervisorRevision"],
                entrypoint=value["entrypoint"],
                stage_identity=tuple(value["stageIdentity"]),
                directory_identities=tuple(
                    (item[0], tuple(item[1])) for item in directories
                ),
                marker_identity=tuple(value["markerIdentity"]),
                executable_identity=tuple(value["executableIdentity"]),
                executable_digest=value["executableDigest"],
            )
            if review.to_bytes() != raw:
                raise ValueError("Windows Worker stage review encoding changed")
            return review
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_record_invalid"
            ) from exc

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-stage-review/v1\0" + self.to_bytes()
        ).hexdigest()


def _valid_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 5
        and all(type(item) is int and item >= 0 for item in value)
        and value[1] > 0
        and value[2] == 1
    )


def review_coding_windows_product_worker_complete_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerStageReviewV1:
    """Review one retained, cleanly stopped stage under offline Product locks."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise OSError("Windows Worker stage review requires a Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_runtime_active"
            )
        with product.gc_gate.read_guard():
            return _review_complete_stage_under_gc_guard(
                product,
                attempt_id=attempt_id,
                lease_owner_revision=quiescence.owner_revision,
            )


def _review_complete_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    """Reuse an already-held offline Package lease and Product GC gate."""

    product.assert_root_gc_authority_current()
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    if len(matches) != 1:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_attempt_unavailable"
        )
    attempt = matches[0]
    if (
        attempt.observed_debts != ("payload_retained", "launch_intent_retained")
        or attempt.native_phase != "settled"
        or attempt.supervisor_phase != "stopped"
        or attempt.native_revision is None
        or attempt.supervisor_revision is None
        or attempt.payload_directory_identity is None
    ):
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_settlement_unverified"
        )
    intent = _read_intent_under_gc_guard(product, attempt_id)
    if intent is None:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_intent_missing"
        )
    review = _review_stage_bytes(
        product,
        attempt_id=attempt_id,
        expected_stage=attempt.payload_directory_identity,
        intent=intent,
        lease_owner_revision=lease_owner_revision,
        native_revision=attempt.native_revision,
        supervisor_revision=attempt.supervisor_revision,
    )
    product.assert_root_gc_authority_current()
    return review


def _review_stage_bytes(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: CodingWindowsWorkerLaunchIntentV1,
    lease_owner_revision: int,
    native_revision: int,
    supervisor_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    captured = _capture_stage_bytes(
        product,
        attempt_id=attempt_id,
        expected_stage=expected_stage,
        intent=intent,
    )
    return CodingWindowsWorkerStageReviewV1(
        attempt_id=attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=lease_owner_revision,
        native_revision=native_revision,
        supervisor_revision=supervisor_revision,
        entrypoint=captured.entrypoint,
        stage_identity=captured.stage_identity,
        directory_identities=captured.directory_identities,
        marker_identity=captured.marker_identity,
        executable_identity=captured.executable_identity,
        executable_digest=captured.executable_digest,
    )


def _capture_stage_bytes(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: CodingWindowsWorkerLaunchIntentV1,
) -> _CapturedStageBytesV1:
    """Verify exact retained members without assuming a termination cause."""

    if type(intent) is not CodingWindowsWorkerLaunchIntentV1:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_intent_invalid"
        )
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            _require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise CodingWindowsWorkerStageReviewError(
                    "coding_worker_stage_review_root_changed"
                )
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                stage_identity = _require_direct(stage, acl, directory=True)
                if (
                    stage_identity[:2] != expected_stage
                    or stage_identity[:2] != intent.stage_identity
                    or _identity(windows_stat_at(root, stage_name)) != stage_identity
                ):
                    raise CodingWindowsWorkerStageReviewError(
                        "coding_worker_stage_review_stage_changed"
                    )
                raw_marker, marker_identity = _read_checked_file(
                    stage,
                    _MARKER,
                    acl,
                    maximum_bytes=_MAX_MARKER_BYTES,
                )
                entrypoint, marker_payload_size = _verify_marker(
                    raw_marker, intent=intent, stage_identity=expected_stage
                )
                parts = entrypoint.split("/")
                if set(windows_listdir_at(stage)) != {_MARKER, parts[0]}:
                    raise CodingWindowsWorkerStageReviewError(
                        "coding_worker_stage_review_tree_changed"
                    )
                current = stage
                children: list[int] = []
                directory_identities: list[tuple[str, FileIdentity]] = []
                try:
                    for index, name in enumerate(parts[:-1]):
                        child = open_windows_directory(
                            name,
                            dir_fd=current,
                            share_delete=False,
                            read_control=True,
                        )
                        children.append(child)
                        identity = _require_direct(child, acl, directory=True)
                        if _identity(windows_stat_at(current, name)) != identity or set(
                            windows_listdir_at(child)
                        ) != {parts[index + 1]}:
                            raise CodingWindowsWorkerStageReviewError(
                                "coding_worker_stage_review_tree_changed"
                            )
                        directory_identities.append(
                            ("/".join(parts[: index + 1]), identity)
                        )
                        current = child
                    executable, executable_identity = _read_checked_file(
                        current,
                        parts[-1],
                        acl,
                        maximum_bytes=_MAX_PAYLOAD_BYTES,
                    )
                    executable_digest = sha256(executable).hexdigest()
                    if (
                        executable_digest != intent.payload_digest
                        or len(executable) != marker_payload_size
                    ):
                        raise CodingWindowsWorkerStageReviewError(
                            "coding_worker_stage_review_payload_changed"
                        )
                finally:
                    for child in reversed(children):
                        os.close(child)
                if (
                    _identity(os.fstat(stage)) != stage_identity
                    or _identity(windows_stat_at(root, stage_name)) != stage_identity
                    or set(windows_listdir_at(stage)) != {_MARKER, parts[0]}
                ):
                    raise CodingWindowsWorkerStageReviewError(
                        "coding_worker_stage_review_stage_changed"
                    )
                return _CapturedStageBytesV1(
                    entrypoint=entrypoint,
                    stage_identity=stage_identity,
                    directory_identities=tuple(directory_identities),
                    marker_identity=marker_identity,
                    executable_identity=executable_identity,
                    executable_digest=executable_digest,
                )
            finally:
                os.close(stage)


def _verify_marker(
    raw: bytes,
    *,
    intent: CodingWindowsWorkerLaunchIntentV1,
    stage_identity: tuple[int, int],
) -> tuple[str, int]:
    if type(intent) is not CodingWindowsWorkerLaunchIntentV1:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_intent_invalid"
        )
    try:
        document = json.loads(raw)
        if type(document) is not dict or type(document.get("entrypoint")) is not str:
            raise ValueError("Worker marker shape changed")
        entrypoint = document["entrypoint"]
        if canonical_plugin_relative_path(entrypoint).as_posix() != entrypoint:
            raise ValueError("Worker marker path changed")
        payload_size = _marker_payload_size(document)
        expected = _marker_bytes(
            attempt_id=intent.attempt_id,
            entrypoint=entrypoint,
            owner_id=intent.owner_id,
            payload_digest=intent.payload_digest,
            payload_size=payload_size,
            receipt_fingerprint=intent.receipt_fingerprint,
            stage_identity=stage_identity,
        )
        if raw != expected:
            raise ValueError("Worker marker bytes changed")
        return entrypoint, payload_size
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_marker_changed"
        ) from exc


def _marker_payload_size(document: dict[str, object]) -> int:
    value = document.get("payloadSize")
    if type(value) is not int or not 0 < value <= _MAX_PAYLOAD_BYTES:
        raise ValueError("Worker marker payload size changed")
    return value


def _read_checked_file(
    parent: int,
    name: str,
    acl: WindowsPrivateDirectoryAcl,
    *,
    maximum_bytes: int,
) -> tuple[bytes, FileIdentity]:
    descriptor = open_windows_regular_file_at(
        parent, name, create_new=False, write=False, read_control=True
    )
    try:
        before = _require_direct(descriptor, acl, directory=False)
        if before[3] > maximum_bytes:
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_file_too_large"
            )
        raw = bytearray()
        while len(raw) <= maximum_bytes:
            chunk = os.read(descriptor, min(_READ_CHUNK, maximum_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if (
            len(raw) != before[3]
            or _require_direct(descriptor, acl, directory=False) != before
            or _identity(windows_stat_at(parent, name)) != before
        ):
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_file_changed"
            )
        return bytes(raw), before
    finally:
        os.close(descriptor)


def _require_direct(
    descriptor: int, acl: WindowsPrivateDirectoryAcl, *, directory: bool
) -> FileIdentity:
    acl.validate(descriptor)
    metadata = os.fstat(descriptor)
    attributes = getattr(metadata, "st_file_attributes", None)
    allowed = _DIRECTORY_ATTRIBUTES if directory else _FILE_ATTRIBUTES
    streams = (
        windows_directory_stream_names(descriptor)
        if directory
        else windows_regular_file_stream_names(descriptor)
    )
    if (
        type(attributes) is not int
        or attributes == 0
        or attributes & ~allowed
        or bool(attributes & 0x00000010) != directory
        or metadata.st_nlink != 1
        or (
            not stat.S_ISDIR(metadata.st_mode)
            if directory
            else not stat.S_ISREG(metadata.st_mode)
        )
        or any(stream.casefold() != "::$data" for stream in streams)
    ):
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_unsafe_member"
        )
    return _identity(metadata)


def _identity(metadata: os.stat_result) -> FileIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


__all__ = [
    "CodingWindowsWorkerStageReviewError",
    "CodingWindowsWorkerStageReviewV1",
    "review_coding_windows_product_worker_complete_stage",
]
