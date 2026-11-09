"""Fixed Windows archive-expiry execution in the existing PM action family.

Code supplies original domain policy and records. The borrowed restore scope,
Journal/receipts and native Archive/Tree IO remain their original authorities.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Generic, Literal, Protocol, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._record_sequence import scan_numbered_revisions
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_flush_directory,
    windows_listdir_at,
    windows_rename_open_directory_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._private_data_backup_windows import (
    WindowsArchiveExpiryIO,
    WindowsPrivateArchiveSnapshot,
)
from ._private_data_expiry import (
    ExpiryAdvance,
    ExpiryHistoryEvent,
    ExpiryPlan,
    validate_expiry_history,
)
from .records import PluginInstallationKeyV1


class _ReceiptScope(Protocol):
    @property
    def state_fd(self) -> int: ...
    def _require_active(self) -> None: ...


class _ExpiryEvent(ExpiryHistoryEvent, Protocol):
    @property
    def archive(self) -> WindowsPrivateArchiveSnapshot | None: ...
    @property
    def receipt(self) -> object | None: ...
    def to_dict(self) -> dict[str, object]: ...


_PlanT = TypeVar("_PlanT", bound=ExpiryPlan)
_ConfirmationT = TypeVar("_ConfirmationT")
_ArchiveT = TypeVar("_ArchiveT", bound=WindowsPrivateArchiveSnapshot)
_EventT = TypeVar("_EventT", bound=_ExpiryEvent)


class WindowsPrivateExpiryTransaction(
    ExpiryAdvance[_EventT], Generic[_PlanT, _ConfirmationT, _ArchiveT, _EventT]
):
    """One fixed original expiry action, no added state or runtime policy table."""

    __slots__ = ()
    _label: ClassVar[str]
    _tree_io: ClassVar[PrivateWindowsTreeIO]
    _archive_io: ClassVar[WindowsArchiveExpiryIO]

    def begin(
        self, plan: _PlanT, confirmation: _ConfirmationT, archive: _ArchiveT
    ) -> _EventT:
        raise NotImplementedError

    def advance(
        self, prior: _EventT, phase: Literal["renamed", "completed"]
    ) -> _EventT:
        raise NotImplementedError

    def _backup_parent(self, key: PluginInstallationKeyV1) -> Path:
        raise NotImplementedError

    def _tombstone_name(self, plan: _PlanT, confirmation: _ConfirmationT) -> str:
        raise NotImplementedError

    def _require_pre_effect_archive(
        self, plan: _PlanT, parent_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> _ArchiveT:
        raise NotImplementedError

    def _require_recovery_authority(self, plan: _PlanT) -> None:
        raise NotImplementedError

    def execute_expiry(self, plan: _PlanT, confirmation: _ConfirmationT) -> object:
        events, staged = self._scan()
        if not events or (
            events[-1].plan != plan or events[-1].confirmation != confirmation
        ):
            raise ValueError(f"{self._label} backup expiry is not confirmed")
        current = events[-1]
        parent_path = self._backup_parent(plan.installation_key)
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        tombstone = self._tombstone_name(plan, confirmation)
        with WindowsPrivateDirectoryAcl() as acl:
            with closing_descriptor(
                open_windows_directory(
                    parent_path, share_delete=False, read_control=True
                )
            ) as parent_fd:
                acl.validate(parent_fd)
                if self._tree_io.directory_identity(parent_fd) != parent_identity:
                    raise ValueError(f"{self._label} backup parent changed")
                names = set(windows_listdir_at(parent_fd))
                if plan.backup_id in names and tombstone in names:
                    raise ValueError(f"{self._label} expiry tombstone collides")
                if current.phase == "completed":
                    if (
                        staged is not None
                        or plan.backup_id in names
                        or tombstone in names
                    ):
                        raise ValueError(f"{self._label} expired archive reappeared")
                    self._require_recovery_authority(plan)
                    assert current.receipt is not None
                    return current.receipt
                if current.phase == "confirmed" or (
                    current.phase == "started" and plan.backup_id in names
                ):
                    archive = self._require_pre_effect_archive(plan, parent_fd, acl)
                    if current.phase == "confirmed":
                        current = self.begin(plan, confirmation, archive)
                    elif current.archive != archive:
                        raise ValueError(f"{self._label} backup archive changed")
                self._require_recovery_authority(plan)
                if current.phase == "started":
                    current = self._rename_or_recover(
                        current, parent_fd, tombstone, acl
                    )
                if current.phase != "renamed" or current.archive is None:
                    raise ValueError(f"{self._label} expiry checkpoint changed")
                names = set(windows_listdir_at(parent_fd))
                if plan.backup_id in names:
                    raise ValueError(f"{self._label} backup archive reappeared")
                if tombstone in names:
                    self._archive_io.remove_expired_archive(
                        parent_fd,
                        parent_path / tombstone,
                        tombstone,
                        current.archive,
                        acl,
                    )
                if (
                    self._tree_io.directory_identity(parent_fd) != parent_identity
                    or plan.backup_id in windows_listdir_at(parent_fd)
                    or tombstone in windows_listdir_at(parent_fd)
                ):
                    raise ValueError(f"{self._label} backup expiry did not settle")
                completed = self.advance(current, "completed")
                assert completed.receipt is not None
                if (
                    self._tree_io.directory_identity(parent_fd) != parent_identity
                    or plan.backup_id in windows_listdir_at(parent_fd)
                    or tombstone in windows_listdir_at(parent_fd)
                ):
                    raise ValueError(f"{self._label} backup expiry did not settle")
                return completed.receipt

    def _rename_or_recover(
        self,
        started: _EventT,
        parent_fd: int,
        tombstone: str,
        acl: WindowsPrivateDirectoryAcl,
    ) -> _EventT:
        archive = started.archive
        if archive is None:
            raise ValueError(f"{self._label} expiry archive is missing")
        names = set(windows_listdir_at(parent_fd))
        original_visible = started.plan.backup_id in names
        tombstone_visible = tombstone in names
        if original_visible and tombstone_visible:
            raise ValueError(f"{self._label} expiry tombstone collides")
        if original_visible:
            with closing_descriptor(
                open_windows_deletion_entry_at(
                    parent_fd, started.plan.backup_id, directory=True
                )
            ) as source_fd:
                self._tree_io.require_directory(
                    source_fd, archive.root_identity[:2], acl
                )
                windows_rename_open_directory_at(
                    parent_fd,
                    source_fd,
                    tombstone,
                    expected_identity=archive.root_identity,
                )
            windows_flush_directory(parent_fd)
        elif not tombstone_visible:
            raise ValueError(f"{self._label} backup archive disappeared")
        self._archive_io.require_expiry_tombstone_subset(
            parent_fd,
            self._backup_parent(started.plan.installation_key) / tombstone,
            tombstone,
            archive,
            acl,
        )
        return self.advance(started, "renamed")

    _event_prefix: ClassVar[str]
    _event_name: ClassVar[re.Pattern[str]]
    _max_events: ClassVar[int]
    _max_event_bytes: ClassVar[int]
    _event_factory: Callable[..., _EventT]
    _confirmation_factory: Callable[..., _ConfirmationT]
    _receipt_factory: Callable[..., object]
    restore: _ReceiptScope
    _receipt_io: ClassVar[WindowsPrivateReceiptIO]

    @property
    def _state_root(self) -> Path:
        raise NotImplementedError

    def _decode_event(self, raw: bytes) -> _EventT:
        raise NotImplementedError

    def events(self) -> tuple[_EventT, ...]:
        events, staged = self._scan()
        if staged is not None:
            raise ValueError(f"{self._label} backup expiry event needs recovery")
        return events

    def _append(
        self,
        before: tuple[_EventT, ...],
        staged: int | None,
        event: _EventT,
    ) -> _EventT:
        self.restore._require_active()
        if len(before) >= self._max_events or staged not in {None, event.revision}:
            raise ValueError(f"{self._label} backup expiry event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > self._max_event_bytes:
            raise ValueError(f"{self._label} backup expiry event is too large")
        self._receipt_io.write_private_receipt(
            self._event_path(event.revision),
            payload,
            maximum_bytes=self._max_event_bytes,
        )
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError(f"{self._label} backup expiry event changed")
        return event

    def _scan(
        self,
    ) -> tuple[tuple[_EventT, ...], int | None]:
        self.restore._require_active()
        published_count, staged_revision = scan_numbered_revisions(
            windows_listdir_at(self.restore.state_fd),
            prefix=self._event_prefix,
            pattern=self._event_name,
            max_records=self._max_events,
            unexpected_member=f"{self._label} backup expiry member is unexpected",
            invalid_revision=f"{self._label} backup expiry revision changed",
            invalid_sequence=f"{self._label} backup expiry sequence changed",
        )
        events: list[_EventT] = []
        for revision in range(1, published_count + 1):
            raw = self._receipt_io.read_private_receipt(
                self._event_path(revision), maximum_bytes=self._max_event_bytes
            )
            if raw is None:
                raise ValueError(f"{self._label} backup expiry event disappeared")
            event = self._decode_event(raw)
            if (
                event.revision != revision
                or raw != canonical_json_bytes(event.to_dict()) + b"\n"
            ):
                raise ValueError(f"{self._label} backup expiry event changed")
            events.append(event)
        validate_expiry_history(tuple(events), label=self._label)
        return tuple(events), staged_revision

    def _event_path(self, revision: int) -> Path:
        return self._state_root / f"{self._event_prefix}{revision:08d}.json"

    def _confirm_current(
        self, plan: _PlanT, *, actor_id: str, policy_revision: str
    ) -> _ConfirmationT:
        confirmation = self._confirmation_factory(
            plan, actor_id=actor_id, policy_revision=policy_revision
        )
        events, staged = self._scan()
        if events and events[-1].phase != "completed":
            if staged is not None:
                raise ValueError(f"{self._label} backup expiry event needs recovery")
            if events[-1].plan == plan and events[-1].confirmation == confirmation:
                return confirmation
            raise ValueError(f"Another {self._label} backup expiry is unfinished")
        if events and events[-1].plan == plan:
            if staged is not None or events[-1].confirmation != confirmation:
                raise ValueError(f"{self._label} backup expiry already completed")
            return confirmation
        if any(
            event.phase == "completed" and event.plan.backup_id == plan.backup_id
            for event in events
        ):
            raise ValueError(f"{self._label} backup expiry already completed")
        event = self._event_factory(
            revision=len(events) + 1,
            phase="confirmed",
            plan=plan,
            confirmation=confirmation,
        )
        self._append(events, staged, event)
        return confirmation

    def _begin_current(
        self, plan: _PlanT, confirmation: _ConfirmationT, archive: _ArchiveT
    ) -> _EventT:
        events, staged = self._scan()
        if not events or (
            events[-1].plan != plan or events[-1].confirmation != confirmation
        ):
            raise ValueError(f"{self._label} backup expiry confirmation changed")
        prior = events[-1]
        if prior.phase != "confirmed":
            if staged is not None or prior.archive != archive:
                raise ValueError(f"{self._label} backup expiry archive changed")
            return prior
        event = self._event_factory(
            revision=len(events) + 1,
            phase="started",
            plan=plan,
            confirmation=confirmation,
            archive=archive,
        )
        return self._append(events, staged, event)

    def _append_current(
        self, before: tuple[_EventT, ...], staged: int | None, event: _EventT
    ) -> _EventT:
        return self._append(before, staged, event)
