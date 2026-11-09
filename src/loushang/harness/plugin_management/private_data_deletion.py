"""Confirmed delegation to an exact Plugin-private-data domain owner.

The coordinator has no filesystem or GC authority. The injected domain owner
must revalidate the plan at mutation time and durably record its own receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, Literal, Protocol, Self, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_rename_open_directory_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

if TYPE_CHECKING:
    from ._private_data_deletion_windows import WindowsPrivateDeletionTransaction


from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_tree_posix import (
    PrivatePosixTreeIO,
)
from loushang.harness.resources.packages._tree_observation import (
    PrivateTreeSnapshot,
    metadata_identity,
    require_tree_subset,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _entry_exists,
    _open_directory,
    _rename_directory_noreplace,
)

PRIVATE_DATA_DELETION_VERSION = 1
PrivateDataDeletionDisposition = Literal["deleted", "already_absent"]


def _require_text(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty")


def _require_sha256(value: str, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionPlanV1:
    installation_key: PluginInstallationKeyV1
    owner_id: str
    target_id: str
    plan_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Private-data deletion requires an Installation key")
        _require_text(self.owner_id, name="private-data owner id")
        _require_text(self.target_id, name="private-data target id")
        if (
            type(self.plan_version) is not int
            or self.plan_version != PRIVATE_DATA_DELETION_VERSION
        ):
            raise ValueError("Unsupported private-data deletion plan")

    @property
    def fingerprint(self) -> str:
        document = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(
            b"loushang.plugin-private-data-deletion-plan/v1\0" + document
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "installationKey": self.installation_key.to_dict(),
            "ownerId": self.owner_id,
            "planVersion": self.plan_version,
            "targetId": self.target_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionPlanV1:
        if type(value) is not dict or set(value) != {
            "installationKey",
            "ownerId",
            "planVersion",
            "targetId",
        }:
            raise ValueError("Private-data deletion plan fields are invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            owner_id=value["ownerId"],
            target_id=value["targetId"],
            plan_version=value["planVersion"],
        )


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionConfirmationV1:
    """Separate operator confirmation bound to one exact previewed plan."""

    plan_fingerprint: str
    confirmation_id: str
    confirmation_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.plan_fingerprint, name="confirmed plan fingerprint")
        _require_text(self.confirmation_id, name="private-data confirmation id")
        if (
            type(self.confirmation_version) is not int
            or self.confirmation_version != PRIVATE_DATA_DELETION_VERSION
        ):
            raise ValueError("Unsupported private-data deletion confirmation")

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmationId": self.confirmation_id,
            "confirmationVersion": self.confirmation_version,
            "planFingerprint": self.plan_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionConfirmationV1:
        if type(value) is not dict or set(value) != {
            "confirmationId",
            "confirmationVersion",
            "planFingerprint",
        }:
            raise ValueError("Private-data confirmation fields are invalid")
        return cls(
            plan_fingerprint=value["planFingerprint"],
            confirmation_id=value["confirmationId"],
            confirmation_version=value["confirmationVersion"],
        )


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionReceiptV1:
    """Domain-owned durable result; Package GC cannot issue this receipt."""

    installation_key: PluginInstallationKeyV1
    owner_id: str
    target_id: str
    plan_fingerprint: str
    confirmation_id: str
    receipt_id: str
    disposition: PrivateDataDeletionDisposition
    receipt_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Private-data receipt requires an Installation key")
        for value, name in (
            (self.owner_id, "private-data owner id"),
            (self.target_id, "private-data target id"),
            (self.confirmation_id, "private-data confirmation id"),
            (self.receipt_id, "private-data receipt id"),
        ):
            _require_text(value, name=name)
        _require_sha256(self.plan_fingerprint, name="private-data plan fingerprint")
        if self.disposition not in {"deleted", "already_absent"}:
            raise ValueError("Unsupported private-data deletion disposition")
        if (
            type(self.receipt_version) is not int
            or self.receipt_version != PRIVATE_DATA_DELETION_VERSION
        ):
            raise ValueError("Unsupported private-data deletion receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmationId": self.confirmation_id,
            "disposition": self.disposition,
            "installationKey": self.installation_key.to_dict(),
            "ownerId": self.owner_id,
            "planFingerprint": self.plan_fingerprint,
            "receiptId": self.receipt_id,
            "receiptVersion": self.receipt_version,
            "targetId": self.target_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionReceiptV1:
        if type(value) is not dict or set(value) != {
            "confirmationId",
            "disposition",
            "installationKey",
            "ownerId",
            "planFingerprint",
            "receiptId",
            "receiptVersion",
            "targetId",
        }:
            raise ValueError("Private-data deletion receipt fields are invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            owner_id=value["ownerId"],
            target_id=value["targetId"],
            plan_fingerprint=value["planFingerprint"],
            confirmation_id=value["confirmationId"],
            receipt_id=value["receiptId"],
            disposition=value["disposition"],
            receipt_version=value["receiptVersion"],
        )


class PrivateDataDeletionTarget(PrivateTreeSnapshot, Protocol):
    @property
    def target_id(self) -> str: ...


_TargetT_co = TypeVar("_TargetT_co", bound=PrivateDataDeletionTarget, covariant=True)


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionEventV1(Generic[_TargetT_co]):
    """Deletion fact; Product subclasses bind target type and the original schema."""

    revision: int
    phase: Literal["started", "renamed", "completed"]
    plan: PluginPrivateDataDeletionPlanV1
    confirmation: PluginPrivateDataDeletionConfirmationV1
    target: _TargetT_co
    receipt: PluginPrivateDataDeletionReceiptV1 | None = None
    record_version: int = 1
    target_type: ClassVar[type[PrivateDataDeletionTarget] | None] = None
    schema: ClassVar[RecordSchema | None] = None

    def __post_init__(self) -> None:
        if self.target_type is None:
            raise TypeError("Private-data deletion target binding is required")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Private-data deletion revision is invalid")
        if (
            self.phase not in {"started", "renamed", "completed"}
            or self.record_version != 1
        ):
            raise ValueError("Private-data deletion event phase is invalid")
        if (
            not isinstance(self.plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(
                self.confirmation, PluginPrivateDataDeletionConfirmationV1
            )
            or not isinstance(self.target, self.target_type)
            or self.plan.target_id != self.target.target_id
            or self.confirmation.plan_fingerprint != self.plan.fingerprint
        ):
            raise ValueError("Private-data deletion event target changed")
        if self.phase in {"started", "renamed"}:
            if self.receipt is not None:
                raise ValueError("Unfinished deletion cannot claim a receipt")
            if self.phase == "renamed" and self.target.root_identity is None:
                raise ValueError("Absent deletion target cannot be renamed")
        elif (
            not isinstance(self.receipt, PluginPrivateDataDeletionReceiptV1)
            or self.receipt.installation_key != self.plan.installation_key
            or self.receipt.owner_id != self.plan.owner_id
            or self.receipt.target_id != self.plan.target_id
            or self.receipt.plan_fingerprint != self.plan.fingerprint
            or self.receipt.confirmation_id != self.confirmation.confirmation_id
        ):
            raise ValueError("Private-data deletion receipt changed")

    def to_dict(self) -> dict[str, object]:
        return self._record_schema().encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        schema = cls._record_schema()
        if type(value) is not dict or set(value) != schema.keys:
            raise ValueError("Private-data deletion event fields are invalid")
        return schema.decode(cls, value)

    @classmethod
    def _record_schema(cls) -> RecordSchema:
        if cls.schema is None:
            raise TypeError("Private-data deletion record schema is required")
        return cls.schema


def latest_deleted_target_receipt(
    events: Sequence[PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]],
    key: PluginInstallationKeyV1,
    target_id: str,
) -> PluginPrivateDataDeletionReceiptV1 | None:
    """Only the latest event for this Installation may prove this deletion."""
    for event in reversed(events):
        if event.plan.installation_key != key:
            continue
        if (
            event.phase == "completed"
            and event.target.target_id == target_id
            and event.receipt is not None
            and event.receipt.disposition == "deleted"
        ):
            return event.receipt
        return None
    return None


class PluginPrivateDataDeletionOwnerPort(Protocol):
    """Exact data-domain owner, responsible for mutation and durable replay."""

    def plan_for(
        self, key: PluginInstallationKeyV1
    ) -> PluginPrivateDataDeletionPlanV1: ...

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1: ...


class PluginPrivateDataDeletionReceiptLookupPort(Protocol):
    """Optional domain-owned read for replay after a target was deleted."""

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None: ...


class PluginPrivateDataConfirmationAuthorityPort(Protocol):
    """Product/operator authority that verifies an independently issued confirmation."""

    def is_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> bool: ...


class PluginPrivateDataDeletionCoordinator:
    """Validates a separate confirmation and delegates; never deletes itself."""

    def __init__(
        self,
        owner: PluginPrivateDataDeletionOwnerPort,
        *,
        confirmation_authority: PluginPrivateDataConfirmationAuthorityPort,
    ) -> None:
        if not all(
            callable(getattr(owner, name, None))
            for name in ("plan_for", "delete_confirmed")
        ):
            raise TypeError("Private-data deletion domain owner is required")
        if not callable(getattr(confirmation_authority, "is_confirmed", None)):
            raise TypeError("Private-data confirmation authority is required")
        self._owner = owner
        self._confirmation_authority = confirmation_authority

    def preview(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        if not isinstance(key, PluginInstallationKeyV1):
            raise TypeError("Private-data deletion requires an Installation key")
        plan = self._owner.plan_for(key)
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1):
            raise TypeError("Private-data owner must return a deletion plan")
        if plan.installation_key != key:
            raise ValueError("Private-data owner returned a foreign plan")
        return plan

    def delete(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1):
            raise TypeError("Private-data deletion plan is required")
        if not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1):
            raise TypeError("Separate private-data deletion confirmation is required")
        if confirmation.plan_fingerprint != plan.fingerprint:
            raise ValueError("Private-data confirmation does not match the plan")
        replay: PluginPrivateDataDeletionReceiptV1 | None = None
        if self.preview(plan.installation_key) != plan:
            lookup = getattr(self._owner, "receipt_for", None)
            if callable(lookup):
                replay = lookup(plan, confirmation)
            if replay is None:
                raise ValueError("Private-data deletion plan is stale")
        if self._confirmation_authority.is_confirmed(plan, confirmation) is not True:
            raise ValueError("Private-data confirmation is not authorized")
        receipt = (
            replay
            if replay is not None
            else self._owner.delete_confirmed(plan, confirmation)
        )
        if not isinstance(receipt, PluginPrivateDataDeletionReceiptV1) or (
            receipt.installation_key != plan.installation_key
            or receipt.owner_id != plan.owner_id
            or receipt.target_id != plan.target_id
            or receipt.plan_fingerprint != plan.fingerprint
            or receipt.confirmation_id != confirmation.confirmation_id
        ):
            raise ValueError("Private-data owner returned a mismatched receipt")
        return receipt


class PrivateDataDeletionCheckpoint(Protocol):
    @property
    def target(self) -> PrivateTreeSnapshot: ...

    @property
    def phase(self) -> str: ...


_CheckpointT = TypeVar("_CheckpointT", bound=PrivateDataDeletionCheckpoint)


def remove_started_private_tree(
    root: Path,
    started: _CheckpointT,
    *,
    io: PrivatePosixTreeIO,
    capture: Callable[[Path], PrivateTreeSnapshot],
    make_tombstone_name: Callable[[], str],
    record_renamed: Callable[[_CheckpointT], _CheckpointT],
) -> tuple[PrivateDataDeletionDisposition, _CheckpointT]:
    """Caller retains its exact confirmation, quiescence and action history."""
    target = started.target
    current = capture(root)
    if target.root_identity is None:
        if current.root_identity is not None:
            raise ValueError(f"Absent {io.label} private-data target changed")
        return "already_absent", started

    tombstone_name = make_tombstone_name()
    parent = root.parent
    with closing_descriptor(_open_directory(parent)) as parent_fd:
        parent_identity = metadata_identity(os.fstat(parent_fd))
        if parent_identity != metadata_identity(parent.lstat()):
            raise ValueError(f"{io.label} private-data parent changed")
        tombstone = parent / tombstone_name
        try:
            tombstone_metadata = os.stat(
                tombstone_name, dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            tombstone_metadata = None
        if tombstone_metadata is None:
            if current.root_identity is None:
                if started.phase != "renamed":
                    raise ValueError(f"{io.label} private-data deletion is ambiguous")
                return "deleted", started
            if started.phase != "started":
                raise ValueError(f"{io.label} private-data tombstone disappeared")
            if current != target:
                raise ValueError(
                    f"{io.label} private-data target changed before rename"
                )
            source_metadata = os.stat(
                root.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if metadata_identity(source_metadata) != target.root_identity:
                raise ValueError(f"{io.label} private-data target identity changed")
            _rename_directory_noreplace(parent_fd, root.name, parent_fd, tombstone_name)
            os.fsync(parent_fd)
        elif current.root_identity is not None:
            raise ValueError(f"{io.label} private-data root and tombstone coexist")
        with closing_descriptor(
            _open_directory(tombstone_name, dir_fd=parent_fd)
        ) as tombstone_fd:
            metadata = os.fstat(tombstone_fd)
            if (metadata.st_dev, metadata.st_ino) != target.root_identity[:2]:
                raise ValueError(f"{io.label} private-data tombstone identity changed")
            renamed = record_renamed(started)
            remaining = capture(tombstone)
            require_tree_subset(remaining, target, label=f"{io.label} private-data")
            io.remove_members(tombstone_fd, remaining.members, target)
            if os.listdir(tombstone_fd):
                raise ValueError(f"{io.label} private-data tombstone is not empty")
            os.fsync(tombstone_fd)
        if (
            os.stat(tombstone_name, dir_fd=parent_fd, follow_symlinks=False).st_ino
            != target.root_identity[1]
        ):
            raise ValueError(f"{io.label} private-data tombstone changed")
        os.rmdir(tombstone_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        if _entry_exists(parent_fd, root.name):
            raise ValueError(f"{io.label} private-data root was recreated")
        return "deleted", renamed


_DeletionTargetT = TypeVar("_DeletionTargetT", bound=PrivateDataDeletionTarget)
_DeletionEventT = TypeVar(
    "_DeletionEventT", bound=PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]
)


class WindowsPrivateTreeCapture(Protocol):
    def __call__(
        self, path: Path, *, expected_root: tuple[int, int]
    ) -> PrivateTreeSnapshot: ...


def remove_started_windows_private_tree(
    root: Path,
    started: _CheckpointT,
    *,
    io: PrivateWindowsTreeIO,
    capture_current: Callable[[], PrivateTreeSnapshot],
    capture: WindowsPrivateTreeCapture,
    make_tombstone_name: Callable[[], str],
    current_start: Callable[[], _CheckpointT | None],
    record_renamed: Callable[[_CheckpointT], _CheckpointT],
) -> PrivateDataDeletionDisposition:
    """Keep the original Windows rename/phase/handle ordering; caller keeps its fence."""
    target = started.target
    if target.root_identity is None:
        if capture_current() != target:
            raise ValueError(f"{io.label} absent target changed")
        return "already_absent"

    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    tombstone_name = make_tombstone_name()
    with WindowsPrivateDirectoryAcl() as exact_acl:
        with closing_descriptor(
            open_windows_directory(root.parent, share_delete=False, read_control=True)
        ) as parent_fd:
            io.require_directory(parent_fd, parent_identity, exact_acl)
            names = set(windows_listdir_at(parent_fd))
            root_present = root.name in names
            tombstone_present = tombstone_name in names
            if root_present and tombstone_present:
                raise ValueError(f"{io.label} root and tombstone coexist")
            if not root_present and not tombstone_present:
                pending = current_start()
                if pending is None or pending.phase != "renamed":
                    raise ValueError(f"{io.label} deletion is ambiguous")
                return "deleted"
            if root_present:
                if current_start() != started:
                    raise ValueError(f"{io.label} deletion root reappeared")
                if capture_current() != target:
                    raise ValueError(f"{io.label} target changed before rename")
                with closing_descriptor(
                    open_windows_deletion_entry_at(parent_fd, root.name, directory=True)
                ) as source_fd:
                    exact_acl.validate(source_fd)
                    io.require_simple_metadata(os.fstat(source_fd), directory=True)
                    io.require_no_named_directory_streams(source_fd)
                    if (
                        metadata_identity(os.fstat(source_fd))[:3]
                        != target.root_identity[:3]
                    ):
                        raise ValueError(f"{io.label} root identity changed")
                    windows_rename_open_directory_at(
                        parent_fd,
                        source_fd,
                        tombstone_name,
                        expected_identity=target.root_identity,
                    )
                windows_flush_directory(parent_fd)
            renamed = record_renamed(started)
            if renamed.phase != "renamed":
                raise ValueError(f"{io.label} rename event changed")
            tombstone = root.parent / tombstone_name
            remaining = capture(tombstone, expected_root=target.root_identity[:2])
            require_tree_subset(remaining, target, label=io.label)
            io.remove_members(tombstone, remaining.members, target)
            if root.name in windows_listdir_at(parent_fd):
                raise ValueError(f"{io.label} root was recreated")
            with closing_descriptor(
                open_windows_deletion_entry_at(
                    parent_fd, tombstone_name, directory=True
                )
            ) as tombstone_fd:
                io.require_directory(tombstone_fd, target.root_identity[:2], exact_acl)
                if windows_listdir_at(tombstone_fd):
                    raise ValueError(f"{io.label} tombstone is not empty")
                windows_delete_open_entry(
                    tombstone_fd,
                    expected_identity=target.root_identity,
                    directory=True,
                )
            windows_flush_directory(parent_fd)
            if root.name in windows_listdir_at(parent_fd) or (
                tombstone_name in windows_listdir_at(parent_fd)
            ):
                raise ValueError(f"{io.label} deletion did not settle")
            io.require_directory(parent_fd, parent_identity, exact_acl)
            return "deleted"


def execute_windows_private_deletion(
    transaction: WindowsPrivateDeletionTransaction[_DeletionTargetT, _DeletionEventT],
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
    *,
    capture_target: Callable[[], _DeletionTargetT],
    remove_started: Callable[[_DeletionEventT], PrivateDataDeletionDisposition],
) -> PluginPrivateDataDeletionReceiptV1:
    """Execute one admitted deletion inside the caller's original offline transaction."""
    replay = transaction.receipt_for(plan, confirmation)
    if replay is not None:
        return replay
    pending = transaction.current_start()
    if pending is None:
        target = capture_target()
        if target.target_id != plan.target_id:
            raise ValueError(f"{transaction._label} deletion plan is stale")
        started = transaction.record_start(plan, confirmation, target)
    elif pending.plan == plan and pending.confirmation == confirmation:
        events = transaction.events()
        started = events[-2] if pending.phase == "renamed" else pending
        if started.phase != "started" or started.target != pending.target:
            raise ValueError(f"{transaction._label} deletion event changed")
    else:
        raise ValueError(f"Another {transaction._label} deletion is unfinished")
    disposition = remove_started(started)
    receipt = PluginPrivateDataDeletionReceiptV1(
        installation_key=plan.installation_key,
        owner_id=plan.owner_id,
        target_id=plan.target_id,
        plan_fingerprint=plan.fingerprint,
        confirmation_id=confirmation.confirmation_id,
        receipt_id=transaction._receipt_id(plan, confirmation),
        disposition=disposition,
    )
    transaction.record_completion(started, receipt)
    return receipt


__all__ = [
    "PRIVATE_DATA_DELETION_VERSION",
    "PluginPrivateDataDeletionConfirmationV1",
    "PluginPrivateDataConfirmationAuthorityPort",
    "PluginPrivateDataDeletionCoordinator",
    "PluginPrivateDataDeletionOwnerPort",
    "PluginPrivateDataDeletionPlanV1",
    "PluginPrivateDataDeletionReceiptLookupPort",
    "PluginPrivateDataDeletionReceiptV1",
]
