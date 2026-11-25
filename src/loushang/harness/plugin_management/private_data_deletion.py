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
from functools import partial
from pathlib import Path
from typing import ClassVar, Generic, Literal, Protocol, Self, TypeVar

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
    RecordField,
    RecordSchema,
    decode_nullable,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _entry_exists,
    _open_directory,
    _rename_directory_noreplace,
)

PRIVATE_DATA_DELETION_VERSION = 1
PrivateDataDeletionDisposition = Literal["deleted", "already_absent"]
_RecordT = TypeVar("_RecordT")


def _read_record(
    schema: RecordSchema,
    construct: Callable[..., _RecordT],
    value: object,
    *,
    error: str,
) -> _RecordT:
    if type(value) is not dict or set(value) != schema.keys:
        raise ValueError(error)
    return schema.decode(construct, value)


_INSTALLATION_KEY = RecordField(
    "installation_key",
    decoder=PluginInstallationKeyV1.from_dict,
    encoder=lambda key: key.to_dict(),
)


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
        return _PLAN_SCHEMA.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionPlanV1:
        return _read_record(
            _PLAN_SCHEMA, cls, value,
            error="Private-data deletion plan fields are invalid",
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
        return _CONFIRMATION_SCHEMA.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionConfirmationV1:
        return _read_record(
            _CONFIRMATION_SCHEMA, cls, value,
            error="Private-data confirmation fields are invalid",
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
        return _RECEIPT_SCHEMA.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataDeletionReceiptV1:
        return _read_record(
            _RECEIPT_SCHEMA, cls, value,
            error="Private-data deletion receipt fields are invalid",
        )

    @classmethod
    def _from_confirmed_plan(
        cls,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        *,
        receipt_id: Callable[[], str],
        disposition: PrivateDataDeletionDisposition,
    ) -> PluginPrivateDataDeletionReceiptV1:
        return cls(
            installation_key=plan.installation_key,
            owner_id=plan.owner_id,
            target_id=plan.target_id,
            plan_fingerprint=plan.fingerprint,
            confirmation_id=confirmation.confirmation_id,
            receipt_id=receipt_id(),
            disposition=disposition,
        )


def _as_is(value: object) -> object:
    return value


_PLAN_SCHEMA = RecordSchema.for_dataclass(
    PluginPrivateDataDeletionPlanV1, _as_is, _INSTALLATION_KEY
)
_CONFIRMATION_SCHEMA = RecordSchema.for_dataclass(
    PluginPrivateDataDeletionConfirmationV1, _as_is
)
_RECEIPT_SCHEMA = RecordSchema.for_dataclass(
    PluginPrivateDataDeletionReceiptV1, _as_is, _INSTALLATION_KEY
)


def confirmed_deletion_digest(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
    *,
    domain: bytes,
) -> str:
    return hashlib.sha256(
        domain
        + plan.fingerprint.encode("ascii")
        + b"\0"
        + confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()


def require_confirmed_deletion_command(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
    *,
    owner_id: str,
    invalid: str,
) -> None:
    if (
        not isinstance(plan, PluginPrivateDataDeletionPlanV1)
        or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
        or plan.owner_id != owner_id
        or confirmation.plan_fingerprint != plan.fingerprint
    ):
        raise ValueError(invalid)


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
        return _read_record(
            cls._record_schema(), cls, value,
            error="Private-data deletion event fields are invalid",
        )

    @classmethod
    def _bind_target_schema(cls, target: RecordField) -> RecordSchema:
        cls.schema = RecordSchema.for_dataclass(
            cls,
            _as_is,
            RecordField(
                "plan",
                decoder=PluginPrivateDataDeletionPlanV1.from_dict,
                encoder=PluginPrivateDataDeletionPlanV1.to_dict,
            ),
            RecordField(
                "confirmation",
                decoder=PluginPrivateDataDeletionConfirmationV1.from_dict,
                encoder=PluginPrivateDataDeletionConfirmationV1.to_dict,
            ),
            target,
            RecordField(
                "receipt",
                decoder=partial(decode_nullable, decoder=PluginPrivateDataDeletionReceiptV1.from_dict),
                encoder=lambda value: None if value is None else value.to_dict(),
            ),
        )
        return cls.schema

    @classmethod
    def _record_schema(cls) -> RecordSchema:
        if cls.schema is None:
            raise TypeError("Private-data deletion record schema is required")
        return cls.schema


def _same_deletion_operation(
    left: PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget],
    right: PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget],
) -> bool:
    return (
        left.plan == right.plan
        and left.confirmation == right.confirmation
        and left.target == right.target
    )


_DeletionEventT = TypeVar(
    "_DeletionEventT", bound=PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]
)


def _find_deletion_completion(
    events: Sequence[_DeletionEventT],
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> _DeletionEventT | None:
    for event in reversed(events):
        if (
            event.phase == "completed"
            and event.plan == plan
            and event.confirmation == confirmation
        ):
            return event
    return None


def _validate_deletion_sequence(
    events: Sequence[PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]],
    *,
    revision_error: str,
    start_error: str,
    rename_error: str,
    completion_error: str,
    owner_id: str | None = None,
    receipt_id: Callable[
        [PluginPrivateDataDeletionPlanV1, PluginPrivateDataDeletionConfirmationV1], str
    ] | None = None,
) -> None:
    """Check retained phase transitions with the native route's receipt policy."""
    pending = None
    seen_confirmations: set[str] = set()
    for revision, event in enumerate(events, start=1):
        if event.revision != revision or (owner_id is not None and event.plan.owner_id != owner_id):
            raise ValueError(revision_error)
        if event.phase == "started":
            if pending is not None or event.confirmation.confirmation_id in seen_confirmations:
                raise ValueError(start_error)
            pending = event
            seen_confirmations.add(event.confirmation.confirmation_id)
        elif event.phase == "renamed":
            if (
                pending is None
                or pending.phase != "started"
                or (receipt_id is not None and pending.target.root_identity is None)
                or not _same_deletion_operation(pending, event)
            ):
                raise ValueError(rename_error)
            pending = event
        else:
            if pending is None or not _same_deletion_operation(event, pending):
                raise ValueError(completion_error)
            receipt = None
            if receipt_id is not None:
                receipt = event.receipt
                if receipt is None or receipt.receipt_id != receipt_id(
                    event.plan, event.confirmation
                ):
                    raise ValueError(completion_error)
            target = pending.target if receipt is not None else event.target
            present = target.root_identity is not None
            if (
                pending.phase != ("renamed" if present else "started")
                or (
                    receipt is not None
                    and receipt.disposition != ("deleted" if present else "already_absent")
                )
            ):
                raise ValueError(completion_error)
            pending = None


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
