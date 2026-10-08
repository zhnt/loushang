"""Offline review of one unlaunched, marker-absent Windows Worker stage.

This is a read-only recovery input. A retained payload directory alone is not
deletion authority; the review refuses any launch, native, or Supervisor
history and captures every direct member through Product-pinned handles.
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
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)

from .package_product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_retirement import (
    _inspect_retirement_attempt_ids_under_gc_guard,
)
from .package_product_worker_windows_stage_review import (
    FileIdentity,
    _identity,
    _read_checked_file,
    _require_direct,
    _valid_identity,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REVIEW_BYTES = 32768
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_DEPTH = 16
_PARTIAL_DEBTS = (
    "payload_retained",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)


class CodingWindowsWorkerPartialStageReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPartialStageReviewV1:
    attempt_id: str
    lease_owner_revision: int
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    entrypoint: str | None
    executable_identity: FileIdentity | None
    executable_digest: str | None

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or not _valid_identity(self.stage_identity)
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) > _MAX_DEPTH
            or not _valid_directories(self.directory_identities)
            or (self.entrypoint is None) != (self.executable_identity is None)
            or (self.entrypoint is None) != (self.executable_digest is None)
        ):
            raise ValueError("Windows Worker partial-stage review is invalid")
        if self.entrypoint is not None:
            try:
                path = canonical_plugin_relative_path(self.entrypoint)
            except ValueError as exc:
                raise ValueError(
                    "Windows Worker partial-stage entrypoint is invalid"
                ) from exc
            parent = "/".join(path.parts[:-1])
            last_directory = (
                self.directory_identities[-1][0] if self.directory_identities else ""
            )
            if (
                path.as_posix() != self.entrypoint
                or parent != last_directory
                or not _valid_identity(self.executable_identity)
                or (
                    self.executable_identity is not None
                    and self.executable_identity[3] > _MAX_PAYLOAD_BYTES
                )
                or type(self.executable_digest) is not str
                or _DIGEST.fullmatch(self.executable_digest) is None
            ):
                raise ValueError("Windows Worker partial-stage file is invalid")

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "attemptId": self.attempt_id,
                "directoryIdentities": [
                    [path, list(identity)]
                    for path, identity in self.directory_identities
                ],
                "entrypoint": self.entrypoint,
                "executableDigest": self.executable_digest,
                "executableIdentity": (
                    None
                    if self.executable_identity is None
                    else list(self.executable_identity)
                ),
                "leaseOwnerRevision": self.lease_owner_revision,
                "stageIdentity": list(self.stage_identity),
                "version": 1,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerPartialStageReviewV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_REVIEW_BYTES:
            raise CodingWindowsWorkerPartialStageReviewError(
                "coding_worker_partial_stage_review_invalid"
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
                    "leaseOwnerRevision",
                    "stageIdentity",
                    "version",
                }
                or value["version"] != 1
            ):
                raise ValueError("Windows Worker partial-stage review fields changed")
            directories = value["directoryIdentities"]
            if (
                type(directories) is not list
                or any(
                    type(item) is not list
                    or len(item) != 2
                    or type(item[1]) is not list
                    for item in directories
                )
                or type(value["stageIdentity"]) is not list
            ):
                raise ValueError("Windows Worker partial-stage identities changed")
            executable_identity = value["executableIdentity"]
            if (
                executable_identity is not None
                and type(executable_identity) is not list
            ):
                raise ValueError("Windows Worker partial-stage file identity changed")
            review = cls(
                attempt_id=value["attemptId"],
                lease_owner_revision=value["leaseOwnerRevision"],
                stage_identity=tuple(value["stageIdentity"]),
                directory_identities=tuple(
                    (item[0], tuple(item[1])) for item in directories
                ),
                entrypoint=value["entrypoint"],
                executable_identity=(
                    None if executable_identity is None else tuple(executable_identity)
                ),
                executable_digest=value["executableDigest"],
            )
            if review.to_bytes() != raw:
                raise ValueError("Windows Worker partial-stage review bytes changed")
            return review
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CodingWindowsWorkerPartialStageReviewError(
                "coding_worker_partial_stage_review_invalid"
            ) from exc

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-partial-stage-review/v1\0"
            + self.to_bytes()
        ).hexdigest()


def _valid_directories(
    directories: tuple[tuple[str, FileIdentity], ...],
) -> bool:
    for index, member in enumerate(directories):
        if (
            type(member) is not tuple
            or len(member) != 2
            or not _valid_identity(member[1])
        ):
            return False
        path = member[0]
        if type(path) is not str:
            return False
        try:
            canonical = canonical_plugin_relative_path(path)
        except ValueError:
            return False
        if canonical.as_posix() != path or len(canonical.parts) != index + 1:
            return False
        if index and "/".join(canonical.parts[:-1]) != directories[index - 1][0]:
            return False
    return True


def review_coding_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerPartialStageReviewV1:
    """Review a marker-absent stage under exclusive Package quiescence."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise OSError("Windows Worker partial-stage review requires a Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerPartialStageReviewError(
                "coding_worker_partial_stage_runtime_active"
            )
        with product.gc_gate.read_guard():
            product.assert_root_gc_authority_current()
            inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(
                product
            )
            matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
            if (
                len(matches) != 1
                or matches[0].observed_debts != _PARTIAL_DEBTS
                or attempt_id in _inspect_retirement_attempt_ids_under_gc_guard(product)
            ):
                raise CodingWindowsWorkerPartialStageReviewError(
                    "coding_worker_partial_stage_history_unverified"
                )
            review = _review_partial_tree(
                product,
                attempt_id=attempt_id,
                expected_stage=matches[0].payload_directory_identity,
                lease_owner_revision=quiescence.owner_revision,
            )
            product.assert_root_gc_authority_current()
            return review


def _review_partial_tree(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int] | None,
    lease_owner_revision: int,
) -> CodingWindowsWorkerPartialStageReviewV1:
    stage_name = "worker-payload-" + attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            _require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise CodingWindowsWorkerPartialStageReviewError(
                    "coding_worker_partial_stage_root_changed"
                )
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                stage_identity = _require_direct(stage, acl, directory=True)
                if (
                    expected_stage is None
                    or stage_identity[:2] != expected_stage
                    or _identity(windows_stat_at(root, stage_name)) != stage_identity
                ):
                    raise CodingWindowsWorkerPartialStageReviewError(
                        "coding_worker_partial_stage_changed"
                    )
                directories: list[tuple[str, FileIdentity]] = []
                opened: list[int] = []
                observed: list[tuple[int, FileIdentity, tuple[str, ...]]] = []
                entrypoint = None
                executable_identity = None
                executable_digest = None
                current = stage
                names_before = tuple(windows_listdir_at(stage))
                try:
                    for depth in range(_MAX_DEPTH + 1):
                        names = tuple(windows_listdir_at(current))
                        if len(names) > 1 or any(
                            name.casefold() == "worker-payload.json" for name in names
                        ):
                            raise CodingWindowsWorkerPartialStageReviewError(
                                "coding_worker_partial_stage_shape_invalid"
                            )
                        if not names:
                            break
                        name = names[0]
                        prefix = directories[-1][0] if directories else ""
                        path = f"{prefix}/{name}" if prefix else name
                        try:
                            canonical = canonical_plugin_relative_path(path)
                        except ValueError as exc:
                            raise CodingWindowsWorkerPartialStageReviewError(
                                "coding_worker_partial_stage_shape_invalid"
                            ) from exc
                        if canonical.as_posix() != path:
                            raise CodingWindowsWorkerPartialStageReviewError(
                                "coding_worker_partial_stage_shape_invalid"
                            )
                        metadata = windows_stat_at(current, name)
                        if stat.S_ISDIR(metadata.st_mode):
                            if depth == _MAX_DEPTH:
                                raise CodingWindowsWorkerPartialStageReviewError(
                                    "coding_worker_partial_stage_depth_exceeded"
                                )
                            child = open_windows_directory(
                                name,
                                dir_fd=current,
                                share_delete=False,
                                read_control=True,
                            )
                            opened.append(child)
                            identity = _require_direct(child, acl, directory=True)
                            if _identity(windows_stat_at(current, name)) != identity:
                                raise CodingWindowsWorkerPartialStageReviewError(
                                    "coding_worker_partial_stage_changed"
                                )
                            directories.append((path, identity))
                            observed.append(
                                (child, identity, tuple(windows_listdir_at(child)))
                            )
                            current = child
                        elif stat.S_ISREG(metadata.st_mode):
                            raw, identity = _read_checked_file(
                                current, name, acl, maximum_bytes=_MAX_PAYLOAD_BYTES
                            )
                            entrypoint = path
                            executable_identity = identity
                            executable_digest = sha256(raw).hexdigest()
                            break
                        else:
                            raise CodingWindowsWorkerPartialStageReviewError(
                                "coding_worker_partial_stage_shape_invalid"
                            )
                    if any(
                        _require_direct(descriptor, acl, directory=True) != identity
                        or tuple(windows_listdir_at(descriptor)) != names
                        for descriptor, identity, names in observed
                    ) or (
                        _identity(os.fstat(stage)) != stage_identity
                        or _identity(windows_stat_at(root, stage_name))
                        != stage_identity
                        or tuple(windows_listdir_at(stage)) != names_before
                    ):
                        raise CodingWindowsWorkerPartialStageReviewError(
                            "coding_worker_partial_stage_changed"
                        )
                    return CodingWindowsWorkerPartialStageReviewV1(
                        attempt_id=attempt_id,
                        lease_owner_revision=lease_owner_revision,
                        stage_identity=stage_identity,
                        directory_identities=tuple(directories),
                        entrypoint=entrypoint,
                        executable_identity=executable_identity,
                        executable_digest=executable_digest,
                    )
                finally:
                    for child in reversed(opened):
                        os.close(child)
            finally:
                os.close(stage)


__all__ = [
    "CodingWindowsWorkerPartialStageReviewError",
    "CodingWindowsWorkerPartialStageReviewV1",
    "review_coding_windows_product_worker_partial_stage",
]
