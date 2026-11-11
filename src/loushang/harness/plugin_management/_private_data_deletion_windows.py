"""Concrete Windows deletion phases over the existing private receipt and native owners.

No Product selection or quiescence is owned here. This is the existing deletion
component's Windows implementation, not a configurable phase graph.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TypeVar

from loushang.harness.journal._record_sequence import scan_numbered_revisions
from loushang.harness.journal.codec import decode_json_record
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from .private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionEventV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionTarget,
)
from .records import PluginInstallationKeyV1

_TargetT = TypeVar("_TargetT", bound=PrivateDataDeletionTarget)
_EventT = TypeVar(
    "_EventT", bound=PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]
)
_DomainEventT = TypeVar(
    "_DomainEventT",
    bound=PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget],
    contravariant=True,
)


class WindowsDeletionDomain(Protocol[_TargetT, _DomainEventT]):
    def require_removed(self, key: PluginInstallationKeyV1) -> None: ...
    def root_for(self, key: PluginInstallationKeyV1) -> Path: ...
    def capture_current(
        self, key: PluginInstallationKeyV1, *, allow_pending: bool = False
    ) -> _TargetT: ...
    def require_staged_unchanged(
        self, key: PluginInstallationKeyV1, target: _TargetT
    ) -> None: ...
    def require_tombstone(self, event: _DomainEventT, *, present: bool) -> None: ...


class WindowsPrivateDeletionTransaction(Generic[_TargetT, _EventT]):
    __slots__ = ()
    state_root: Path
    state_fd: int
    _active: bool
    _label: ClassVar[str]
    _owner_id: ClassVar[str]
    _event_prefix: ClassVar[str]
    _event_name: ClassVar[re.Pattern[str]]
    _max_event_bytes: ClassVar[int]
    _max_events: ClassVar[int]
    _receipt_io: ClassVar[WindowsPrivateReceiptIO]

    @property
    def _event_type(self) -> type[_EventT]:
        raise NotImplementedError

    @property
    def _target_type(self) -> type[_TargetT]:
        raise NotImplementedError

    def _domain(self) -> WindowsDeletionDomain[_TargetT, _EventT]:
        raise NotImplementedError

    def _require_confirmation(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        raise NotImplementedError

    def _receipt_id(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> str:
        raise NotImplementedError

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)

    def _require_active(self) -> None:
        if not self._active:
            raise ValueError(f"{self._label} deletion transaction is closed")

    def events(self) -> tuple[_EventT, ...]:
        """Reject every unpublished event before returning verified history."""

        events, staged = self._scan()
        if staged is not None:
            raise ValueError(f"{self._label} deletion event needs recovery")
        return events

    def current_start(self) -> _EventT | None:
        events = self.events()
        return _open_start(events)

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        for event in reversed(self.events()):
            if (
                event.phase == "completed"
                and event.plan == plan
                and event.confirmation == confirmation
            ):
                return event.receipt
        return None

    def record_start(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        target: _TargetT,
    ) -> _EventT:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or not isinstance(target, self._target_type)
            or plan.owner_id != self._owner_id
            or plan.target_id != target.target_id
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError(f"{self._label} deletion start is foreign")
        self._require_confirmation(plan, confirmation)
        domain = self._domain()
        domain.require_removed(plan.installation_key)
        events, staged = self._scan()
        pending = _open_start(events)
        if pending is not None:
            if staged is not None:
                raise ValueError(f"{self._label} deletion event needs recovery")
            if (
                pending.plan == plan
                and pending.confirmation == confirmation
                and pending.target == target
            ):
                return pending
            raise ValueError(f"Another {self._label} deletion is unfinished")
        if any(
            event.confirmation.confirmation_id == confirmation.confirmation_id
            for event in events
        ):
            raise ValueError(f"{self._label} confirmation was consumed")
        if staged is None:
            if domain.capture_current(plan.installation_key) != target:
                raise ValueError(f"{self._label} deletion target changed")
        else:
            domain.require_staged_unchanged(plan.installation_key, target)
        event = self._event_type(
            revision=len(events) + 1,
            phase="started",
            plan=plan,
            confirmation=confirmation,
            target=target,
        )
        return self._append(events, staged, event)

    def record_renamed(self, started: _EventT) -> _EventT:
        if not isinstance(started, self._event_type):
            raise ValueError(f"{self._label} deletion start is invalid")
        events, staged = self._scan()
        pending = _open_start(events)
        if (
            pending is None
            or started.phase != "started"
            or not _same_operation(pending, started)
        ):
            raise ValueError(f"{self._label} deletion start changed")
        if pending.phase == "renamed":
            if staged is not None or len(events) < 2 or events[-2] != started:
                raise ValueError(f"{self._label} deletion event needs recovery")
            return pending
        if pending != started:
            raise ValueError(f"{self._label} deletion start changed")
        if pending.target.root_identity is None:
            raise ValueError(f"Absent {self._label} target cannot be renamed")
        self._require_confirmation(pending.plan, pending.confirmation)
        domain = self._domain()
        domain.require_tombstone(started, present=True)
        event = self._event_type(
            revision=len(events) + 1,
            phase="renamed",
            plan=pending.plan,
            confirmation=pending.confirmation,
            target=pending.target,
        )
        return self._append(events, staged, event)

    def record_completion(
        self,
        started: _EventT,
        receipt: PluginPrivateDataDeletionReceiptV1,
    ) -> _EventT:
        if not isinstance(started, self._event_type) or not isinstance(
            receipt, PluginPrivateDataDeletionReceiptV1
        ):
            raise ValueError(f"{self._label} deletion completion is invalid")
        events, staged = self._scan()
        pending = _open_start(events)
        if (
            pending is None
            or started.phase != "started"
            or not _same_operation(pending, started)
        ):
            prior = next(
                (
                    event
                    for event in reversed(events)
                    if event.phase == "completed" and _same_operation(event, started)
                ),
                None,
            )
            if prior is not None and prior.receipt == receipt and staged is None:
                return prior
            raise ValueError(f"{self._label} deletion start changed")
        if (
            (pending.target.root_identity is None and pending.phase != "started")
            or (pending.target.root_identity is not None and pending.phase != "renamed")
            or (
                pending.target.root_identity is None
                and receipt.disposition != "already_absent"
            )
            or (
                pending.target.root_identity is not None
                and receipt.disposition != "deleted"
            )
            or receipt.receipt_id
            != self._receipt_id(pending.plan, pending.confirmation)
        ):
            raise ValueError(f"{self._label} deletion terminal phase is invalid")
        self._require_confirmation(pending.plan, pending.confirmation)
        domain = self._domain()
        root = domain.root_for(pending.plan.installation_key)
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"{self._label} deletion root remains present")
        if (
            pending.target.root_identity is None
            and domain.capture_current(
                pending.plan.installation_key, allow_pending=True
            )
            != pending.target
        ):
            raise ValueError(f"{self._label} absent target changed")
        if pending.target.root_identity is not None:
            domain.require_tombstone(pending, present=False)
        event = self._event_type(
            revision=len(events) + 1,
            phase="completed",
            plan=pending.plan,
            confirmation=pending.confirmation,
            target=pending.target,
            receipt=receipt,
        )
        return self._append(events, staged, event)

    def _append(
        self,
        before: tuple[_EventT, ...],
        staged: int | None,
        event: _EventT,
    ) -> _EventT:
        self._require_active()
        if len(before) >= self._max_events or staged not in {None, event.revision}:
            raise ValueError(f"{self._label} deletion event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > self._max_event_bytes:
            raise ValueError(f"{self._label} deletion event is too large")
        path = self._event_path(event.revision)
        self._receipt_io.write_private_receipt(
            path, payload, maximum_bytes=self._max_event_bytes
        )
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError(f"{self._label} deletion event changed")
        return event

    def _scan(
        self,
    ) -> tuple[tuple[_EventT, ...], int | None]:
        self._require_active()
        published_count, staged_revision = scan_numbered_revisions(
            windows_listdir_at(self.state_fd),
            prefix=self._event_prefix,
            pattern=self._event_name,
            max_records=self._max_events,
            unexpected_member=f"{self._label} deletion member is unexpected",
            invalid_revision=f"{self._label} deletion revision is invalid",
            invalid_sequence=f"{self._label} deletion event sequence is invalid",
        )
        events: list[_EventT] = []
        for revision in range(1, published_count + 1):
            raw = self._receipt_io.read_private_receipt(
                self._event_path(revision), maximum_bytes=self._max_event_bytes
            )
            if raw is None:
                raise ValueError(f"{self._label} deletion event disappeared")
            event = self._decode_event(raw)
            if event.revision != revision:
                raise ValueError(f"{self._label} deletion revision changed")
            events.append(event)
        self._validate_sequence(tuple(events))
        return tuple(events), staged_revision

    def _event_path(self, revision: int) -> Path:
        return self.state_root / f"{self._event_prefix}{revision:08d}.json"

    def _validate_sequence(self, events: tuple[_EventT, ...]) -> None:
        validate_windows_deletion_sequence(
            events,
            owner_id=self._owner_id,
            label=self._label,
            receipt_id=self._receipt_id,
        )

    def _decode_event(self, raw: bytes) -> _EventT:
        return decode_windows_deletion_event(raw, self._event_type, label=self._label)


def _same_operation(
    left: _EventT,
    right: _EventT,
) -> bool:
    return (
        left.plan == right.plan
        and left.confirmation == right.confirmation
        and left.target == right.target
    )


def _open_start(
    events: tuple[_EventT, ...],
) -> _EventT | None:
    return events[-1] if events and events[-1].phase != "completed" else None


def validate_windows_deletion_sequence(
    events: tuple[_EventT, ...],
    *,
    owner_id: str,
    label: str,
    receipt_id: Callable[
        [PluginPrivateDataDeletionPlanV1, PluginPrivateDataDeletionConfirmationV1], str
    ],
) -> None:
    pending: _EventT | None = None
    seen_confirmations: set[str] = set()
    for revision, event in enumerate(events, start=1):
        if event.revision != revision or event.plan.owner_id != owner_id:
            raise ValueError(f"{label} deletion event identity changed")
        if event.phase == "started":
            if (
                pending is not None
                or event.confirmation.confirmation_id in seen_confirmations
            ):
                raise ValueError(f"{label} deletion starts conflict")
            pending = event
            seen_confirmations.add(event.confirmation.confirmation_id)
        elif event.phase == "renamed":
            if (
                pending is None
                or pending.phase != "started"
                or pending.target.root_identity is None
                or not _same_operation(pending, event)
            ):
                raise ValueError(f"{label} deletion rename has no start")
            pending = event
        else:
            receipt = event.receipt
            if (
                pending is None
                or not _same_operation(pending, event)
                or receipt is None
                or receipt.receipt_id != receipt_id(event.plan, event.confirmation)
                or (
                    pending.target.root_identity is None
                    and (
                        pending.phase != "started"
                        or receipt.disposition != "already_absent"
                    )
                )
                or (
                    pending.target.root_identity is not None
                    and (pending.phase != "renamed" or receipt.disposition != "deleted")
                )
            ):
                raise ValueError(f"{label} deletion completion has no start")
            pending = None


def decode_windows_deletion_event(
    raw: bytes, event_type: type[_EventT], *, label: str
) -> _EventT:
    event = decode_json_record(
        raw, event_type.from_dict, label=f"{label} deletion event"
    )
    if raw != canonical_json_bytes(event.to_dict()) + b"\n":
        raise ValueError(f"{label} deletion event is noncanonical")
    return event
