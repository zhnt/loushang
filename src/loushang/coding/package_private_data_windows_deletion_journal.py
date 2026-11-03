"""Native, Product-bound Windows Arch private-data deletion event candidate.

One immutable private receipt records each phase. The Product's cross-process
offline gate covers the entire transaction, including future filesystem work.
An unpublished or malformed next event remains visible as recovery debt.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    _windows_arch_current_root_generation,
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
)

_EVENT_NAME = re.compile(r"arch-private-deletion-([0-9]{8})\.json(\.stage)?\Z")
_EVENT_PREFIX = "arch-private-deletion-"
_MAX_EVENT_BYTES = 4 * 1024 * 1024
_MAX_EVENTS = 4096
_OWNER_ID = "coding.arch.private-data:windows-v1"


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        if (
            self.product.state_root
            != resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        ):
            raise ValueError("Windows Coding Arch deletion Product state changed")

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchPrivateDataDeletionTransaction]:
        """Hold one offline Product gate from start through physical effects."""

        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Windows Coding Arch deletion runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard(require_write=True):
                with (
                    self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd
                ):
                    transaction = CodingWindowsArchPrivateDataDeletionTransaction(
                        self.product.state_root,
                        fd,
                        CodingWindowsArchPrivateDataConfirmationOwner(
                            self.layout, self.product
                        ),
                    )
                    try:
                        yield transaction
                    finally:
                        transaction._close()
            self.product.assert_root_gc_authority_current()


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionTransaction:
    state_root: Path
    state_fd: int
    confirmations: CodingWindowsArchPrivateDataConfirmationOwner | None = None
    _active: bool = field(default=True, init=False, repr=False, compare=False)

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)

    def _require_active(self) -> None:
        if not self._active:
            raise ValueError("Windows Coding Arch deletion transaction is closed")

    def events(self) -> tuple[CodingArchPrivateDataDeletionEventV1, ...]:
        """Reject every unpublished event before returning verified history."""

        events, staged = self._scan()
        if staged is not None:
            raise ValueError("Windows Coding Arch deletion event needs recovery")
        return events

    def current_start(self) -> CodingArchPrivateDataDeletionEventV1 | None:
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
        target: CodingArchPrivateDataTargetSnapshotV1,
    ) -> CodingArchPrivateDataDeletionEventV1:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or not isinstance(target, CodingArchPrivateDataTargetSnapshotV1)
            or plan.owner_id != _OWNER_ID
            or plan.target_id != target.target_id
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch deletion start is foreign")
        self._require_confirmation(plan, confirmation)
        owner = self.confirmations
        if owner is None:
            raise ValueError("Windows Coding Arch deletion Product owner is absent")
        product = owner.product
        state = product.desired_state.snapshot().installation(plan.installation_key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
        ):
            raise ValueError("Windows Coding Arch deletion requires Product removal")
        events, staged = self._scan()
        pending = _open_start(events)
        if pending is not None:
            if staged is not None:
                raise ValueError("Windows Coding Arch deletion event needs recovery")
            if (
                pending.plan == plan
                and pending.confirmation == confirmation
                and pending.target == target
            ):
                return pending
            raise ValueError("Another Windows Coding Arch deletion is unfinished")
        if any(
            event.confirmation.confirmation_id == confirmation.confirmation_id
            for event in events
        ):
            raise ValueError("Windows Coding Arch confirmation was consumed")
        if staged is None:
            if _capture_current_target(owner, plan.installation_key) != target:
                raise ValueError("Windows Coding Arch deletion target changed")
        else:
            _require_staged_start_target_unchanged(
                owner, plan.installation_key, target
            )
        event = CodingArchPrivateDataDeletionEventV1(
            revision=len(events) + 1,
            phase="started",
            plan=plan,
            confirmation=confirmation,
            target=target,
        )
        return self._append(events, staged, event)

    def record_renamed(
        self, started: CodingArchPrivateDataDeletionEventV1
    ) -> CodingArchPrivateDataDeletionEventV1:
        if not isinstance(started, CodingArchPrivateDataDeletionEventV1):
            raise ValueError("Windows Coding Arch deletion start is invalid")
        events, staged = self._scan()
        pending = _open_start(events)
        if (
            pending is None
            or started.phase != "started"
            or not _same_operation(pending, started)
        ):
            raise ValueError("Windows Coding Arch deletion start changed")
        if pending.phase == "renamed":
            if staged is not None or len(events) < 2 or events[-2] != started:
                raise ValueError("Windows Coding Arch deletion event needs recovery")
            return pending
        if pending != started:
            raise ValueError("Windows Coding Arch deletion start changed")
        if pending.target.root_identity is None:
            raise ValueError("Absent Windows Coding Arch target cannot be renamed")
        self._require_confirmation(pending.plan, pending.confirmation)
        owner = self.confirmations
        if owner is None:
            raise ValueError("Windows Coding Arch deletion Product owner is absent")
        _require_windows_tombstone(owner, started, present=True)
        event = CodingArchPrivateDataDeletionEventV1(
            revision=len(events) + 1,
            phase="renamed",
            plan=pending.plan,
            confirmation=pending.confirmation,
            target=pending.target,
        )
        return self._append(events, staged, event)

    def record_completion(
        self,
        started: CodingArchPrivateDataDeletionEventV1,
        receipt: PluginPrivateDataDeletionReceiptV1,
    ) -> CodingArchPrivateDataDeletionEventV1:
        if not isinstance(
            started, CodingArchPrivateDataDeletionEventV1
        ) or not isinstance(receipt, PluginPrivateDataDeletionReceiptV1):
            raise ValueError("Windows Coding Arch deletion completion is invalid")
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
            raise ValueError("Windows Coding Arch deletion start changed")
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
            != windows_arch_deletion_receipt_id(pending.plan, pending.confirmation)
        ):
            raise ValueError("Windows Coding Arch deletion terminal phase is invalid")
        self._require_confirmation(pending.plan, pending.confirmation)
        owner = self.confirmations
        if owner is None:
            raise ValueError("Windows Coding Arch deletion Product owner is absent")
        root = coding_arch_installation_private_data_root(
            owner.layout, pending.plan.installation_key
        )
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Windows Coding Arch deletion root remains present")
        if (
            pending.target.root_identity is None
            and _capture_current_target(
                owner, pending.plan.installation_key, allow_pending=True
            )
            != pending.target
        ):
            raise ValueError("Windows Coding Arch absent target changed")
        if pending.target.root_identity is not None:
            _require_windows_tombstone(owner, pending, present=False)
        event = CodingArchPrivateDataDeletionEventV1(
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
        before: tuple[CodingArchPrivateDataDeletionEventV1, ...],
        staged: int | None,
        event: CodingArchPrivateDataDeletionEventV1,
    ) -> CodingArchPrivateDataDeletionEventV1:
        self._require_active()
        if len(before) >= _MAX_EVENTS or staged not in {None, event.revision}:
            raise ValueError("Windows Coding Arch deletion event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > _MAX_EVENT_BYTES:
            raise ValueError("Windows Coding Arch deletion event is too large")
        path = self._event_path(event.revision)
        write_windows_private_receipt(path, payload)
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError("Windows Coding Arch deletion event changed")
        return event

    def _scan(
        self,
    ) -> tuple[tuple[CodingArchPrivateDataDeletionEventV1, ...], int | None]:
        self._require_active()
        published: set[int] = set()
        staged: set[int] = set()
        for name in windows_listdir_at(self.state_fd):
            if not name.startswith(_EVENT_PREFIX):
                continue
            match = _EVENT_NAME.fullmatch(name)
            if match is None:
                raise ValueError("Windows Coding Arch deletion member is unexpected")
            revision = int(match.group(1))
            if revision < 1:
                raise ValueError("Windows Coding Arch deletion revision is invalid")
            (staged if match.group(2) else published).add(revision)
        if (
            len(published) > _MAX_EVENTS
            or len(staged) > 1
            or published != set(range(1, len(published) + 1))
            or (staged and staged != {len(published) + 1})
        ):
            raise ValueError("Windows Coding Arch deletion event sequence is invalid")
        events: list[CodingArchPrivateDataDeletionEventV1] = []
        for revision in range(1, len(published) + 1):
            raw = read_windows_private_receipt(
                self._event_path(revision), maximum_bytes=_MAX_EVENT_BYTES
            )
            if raw is None:
                raise ValueError("Windows Coding Arch deletion event disappeared")
            event = _decode_event(raw)
            if event.revision != revision:
                raise ValueError("Windows Coding Arch deletion revision changed")
            events.append(event)
        _validate_sequence(tuple(events))
        return tuple(events), next(iter(staged)) if staged else None

    def _event_path(self, revision: int) -> Path:
        return self.state_root / f"{_EVENT_PREFIX}{revision:08d}.json"

    def _require_confirmation(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        owner = self.confirmations
        if owner is None or owner.is_confirmed(plan, confirmation) is not True:
            raise ValueError("Windows Coding Arch deletion confirmation is missing")


def _decode_event(raw: bytes) -> CodingArchPrivateDataDeletionEventV1:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        event = CodingArchPrivateDataDeletionEventV1.from_dict(document)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("Windows Coding Arch deletion event is invalid") from exc
    if raw != canonical_json_bytes(event.to_dict()) + b"\n":
        raise ValueError("Windows Coding Arch deletion event is noncanonical")
    return event


def windows_arch_deletion_receipt_id(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> str:
    if confirmation.plan_fingerprint != plan.fingerprint:
        raise ValueError("Windows Coding Arch deletion receipt is foreign")
    return sha256(
        b"loushang.coding-arch-private-data-receipt/v1\0"
        + plan.fingerprint.encode("ascii")
        + b"\0"
        + confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()


def _capture_current_target(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    key: PluginInstallationKeyV1,
    *,
    allow_pending: bool = False,
) -> CodingArchPrivateDataTargetSnapshotV1:
    root = coding_arch_installation_private_data_root(owner.layout, key)
    if allow_pending:
        expected_root = _windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
    else:
        expected_root = inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    if expected_root is None:
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Windows Coding Arch absent target changed")
        if (
            allow_pending
            and _windows_arch_current_root_generation(
                key,
                root,
                owner.product.state_root,
                inspect_windows_product_private_directory_identity(
                    owner.layout.package_root
                ),
                allow_pending=True,
            ).identity
            is not None
        ):
            raise ValueError("Windows Coding Arch absent target changed")
        return CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
            root_identity=None,
            members=(),
        )
    target = _capture_windows_target_snapshot(root, expected_root=expected_root)
    current_root = (
        _windows_arch_current_root_generation(
            key,
            root,
            owner.product.state_root,
            inspect_windows_product_private_directory_identity(
                owner.layout.package_root
            ),
            allow_pending=True,
        ).identity
        if allow_pending
        else inspect_coding_windows_arch_installation_root(
            owner.layout, key, state_root=owner.product.state_root
        )
    )
    if current_root != expected_root:
        raise ValueError("Windows Coding Arch deletion root changed")
    return target


def _require_staged_start_target_unchanged(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    key: PluginInstallationKeyV1,
    target: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    """Recapture a staged start without reading its own unpublished journal."""

    root = coding_arch_installation_private_data_root(owner.layout, key)
    if target.root_path_digest != sha256(os.fsencode(str(root))).hexdigest():
        raise ValueError("Windows Coding Arch deletion target changed")
    if target.root_identity is None:
        try:
            root.lstat()
        except FileNotFoundError:
            return
        raise ValueError("Windows Coding Arch deletion target changed")
    if (
        _capture_windows_target_snapshot(
            root, expected_root=target.root_identity[:2]
        )
        != target
    ):
        raise ValueError("Windows Coding Arch deletion target changed")


def _tombstone_name(started: CodingArchPrivateDataDeletionEventV1) -> str:
    digest = sha256(
        b"loushang.coding-arch-private-data-tombstone/v1\0"
        + started.plan.fingerprint.encode("ascii")
        + b"\0"
        + started.confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()
    return ".deleting-" + digest


def _require_windows_tombstone(
    owner: CodingWindowsArchPrivateDataConfirmationOwner,
    started: CodingArchPrivateDataDeletionEventV1,
    *,
    present: bool,
) -> None:
    target_identity = started.target.root_identity
    if target_identity is None:
        raise ValueError("Windows Coding Arch tombstone requires a present target")
    root = coding_arch_installation_private_data_root(
        owner.layout, started.plan.installation_key
    )
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    generation = _windows_arch_current_root_generation(
        started.plan.installation_key,
        root,
        owner.product.state_root,
        inspect_windows_product_private_directory_identity(owner.layout.package_root),
        allow_pending=True,
    )
    if generation.receipt is None or generation.identity != target_identity[:2]:
        raise ValueError("Windows Coding Arch tombstone root receipt changed")
    with WindowsPrivateDirectoryAcl() as acl:
        parent_fd = open_windows_directory(
            root.parent, share_delete=False, read_control=True
        )
        try:
            acl.validate(parent_fd)
            metadata = os.fstat(parent_fd)
            if (metadata.st_dev, metadata.st_ino) != parent_identity:
                raise ValueError("Windows Coding Arch tombstone parent changed")
            names = set(windows_listdir_at(parent_fd))
            tombstone_name = _tombstone_name(started)
            if root.name in names or (tombstone_name in names) != present:
                raise ValueError("Windows Coding Arch tombstone state changed")
            if present:
                remaining = _capture_windows_target_snapshot(
                    root.parent / tombstone_name,
                    expected_root=target_identity[:2],
                )
                if (
                    remaining.root_identity is None
                    or remaining.root_identity[:3] != target_identity[:3]
                    or remaining.members != started.target.members
                ):
                    raise ValueError("Windows Coding Arch tombstone bytes changed")
            acl.validate(parent_fd)
            current = os.fstat(parent_fd)
            if (current.st_dev, current.st_ino) != parent_identity:
                raise ValueError("Windows Coding Arch tombstone parent changed")
        finally:
            os.close(parent_fd)


def _validate_sequence(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
) -> None:
    pending: CodingArchPrivateDataDeletionEventV1 | None = None
    seen_confirmations: set[str] = set()
    for revision, event in enumerate(events, start=1):
        if event.revision != revision or event.plan.owner_id != _OWNER_ID:
            raise ValueError("Windows Coding Arch deletion event identity changed")
        if event.phase == "started":
            if (
                pending is not None
                or event.confirmation.confirmation_id in seen_confirmations
            ):
                raise ValueError("Windows Coding Arch deletion starts conflict")
            pending = event
            seen_confirmations.add(event.confirmation.confirmation_id)
        elif event.phase == "renamed":
            if (
                pending is None
                or pending.phase != "started"
                or pending.target.root_identity is None
                or not _same_operation(pending, event)
            ):
                raise ValueError("Windows Coding Arch deletion rename has no start")
            pending = event
        else:
            receipt = event.receipt
            if (
                pending is None
                or not _same_operation(pending, event)
                or receipt is None
                or receipt.receipt_id
                != windows_arch_deletion_receipt_id(event.plan, event.confirmation)
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
                raise ValueError("Windows Coding Arch deletion completion has no start")
            pending = None


def _same_operation(
    left: CodingArchPrivateDataDeletionEventV1,
    right: CodingArchPrivateDataDeletionEventV1,
) -> bool:
    return (
        left.plan == right.plan
        and left.confirmation == right.confirmation
        and left.target == right.target
    )


def _open_start(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
) -> CodingArchPrivateDataDeletionEventV1 | None:
    return events[-1] if events and events[-1].phase != "completed" else None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Windows Coding Arch deletion event has duplicate fields")
        result[key] = value
    return result


__all__ = [
    "CodingWindowsArchPrivateDataDeletionJournal",
    "CodingWindowsArchPrivateDataDeletionTransaction",
    "windows_arch_deletion_receipt_id",
]
