"""Native Product-private confirmation and start receipts for Windows expiry.

This candidate records operator acceptance and an exact archive snapshot.
Rename, member deletion, and terminal completion require a separate owner.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
)
from .package_private_data_windows_backup_expiry_preview import (
    CodingWindowsArchPrivateDataBackupExpiryPreview,
)
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
)

_EVENT_PREFIX = "arch-backup-expiry-"
_EVENT_NAME = re.compile(r"arch-backup-expiry-([0-9]{8})\.json(\.stage)?\Z")
_MAX_EVENTS = 4096
_MAX_EVENT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryEventV1:
    revision: int
    phase: Literal["confirmed", "started", "renamed", "completed"]
    plan: CodingArchPrivateDataBackupExpiryPlanV1
    confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1
    archive: CodingWindowsArchBackupArchiveSnapshotV1 | None = None
    receipt: CodingArchPrivateDataBackupExpiryReceiptV1 | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.phase not in {"confirmed", "started", "renamed", "completed"}
            or not isinstance(self.plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                self.confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or self.confirmation.plan_fingerprint != self.plan.fingerprint
            or self.record_version != 1
        ):
            raise ValueError("Windows Coding Arch backup expiry event is invalid")
        if self.phase == "confirmed":
            if self.archive is not None or self.receipt is not None:
                raise ValueError(
                    "Unstarted Windows Coding Arch backup expiry has effects"
                )
            return
        if (
            not isinstance(self.archive, CodingWindowsArchBackupArchiveSnapshotV1)
            or self.archive.root_identity != self.plan.archive_root_identity
            or self.archive.target_id != self.plan.archive_target_id
        ):
            raise ValueError("Windows Coding Arch backup expiry archive changed")
        if self.phase == "completed":
            if self.receipt != CodingArchPrivateDataBackupExpiryReceiptV1.create(
                self.plan, self.confirmation
            ):
                raise ValueError("Windows Coding Arch backup expiry receipt changed")
        elif self.receipt is not None:
            raise ValueError("Unfinished Windows Coding Arch backup expiry has receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "archive": None if self.archive is None else self.archive.to_dict(),
            "confirmation": self.confirmation.to_dict(),
            "phase": self.phase,
            "plan": self.plan.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsArchBackupExpiryEventV1:
        if type(value) is not dict or set(value) != {
            "archive",
            "confirmation",
            "phase",
            "plan",
            "receipt",
            "recordVersion",
            "revision",
        }:
            raise ValueError("Windows Coding Arch backup expiry event fields changed")
        archive = value["archive"]
        receipt = value["receipt"]
        return cls(
            revision=value["revision"],
            phase=value["phase"],
            plan=CodingArchPrivateDataBackupExpiryPlanV1.from_dict(value["plan"]),
            confirmation=CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict(
                value["confirmation"]
            ),
            archive=(
                None
                if archive is None
                else CodingWindowsArchBackupArchiveSnapshotV1.from_dict(archive)
            ),
            receipt=(
                None
                if receipt is None
                else CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(receipt)
            ),
            record_version=value["recordVersion"],
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataBackupExpiryPreview(self.layout, self.product)

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchBackupExpiryTransaction]:
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as restore:
            yield CodingWindowsArchBackupExpiryTransaction(
                self.layout, self.product, restore
            )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryTransaction:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner
    restore: CodingWindowsArchPrivateDataRestoreTransaction

    def events(self) -> tuple[CodingWindowsArchBackupExpiryEventV1, ...]:
        events, staged = self._scan()
        if staged is not None:
            raise ValueError("Windows Coding Arch backup expiry event needs recovery")
        return events

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        if not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1):
            raise ValueError("Windows Coding Arch backup expiry plan is invalid")
        current = CodingWindowsArchPrivateDataBackupExpiryPreview(
            self.layout, self.product
        )._preview_locked(
            self.restore,
            plan.installation_key,
            plan.backup_id,
            plan.confirmation_id,
        )
        if current != plan:
            raise ValueError("Windows Coding Arch backup expiry plan changed")
        confirmation = CodingArchPrivateDataBackupExpiryConfirmationV1.create(
            plan, actor_id=actor_id, policy_revision=policy_revision
        )
        events, staged = self._scan()
        if events and events[-1].phase != "completed":
            if staged is not None:
                raise ValueError(
                    "Windows Coding Arch backup expiry event needs recovery"
                )
            if events[-1].plan == plan and events[-1].confirmation == confirmation:
                return confirmation
            raise ValueError("Another Windows Coding Arch backup expiry is unfinished")
        if events and events[-1].plan == plan:
            if staged is not None or events[-1].confirmation != confirmation:
                raise ValueError("Windows Coding Arch backup expiry already completed")
            return confirmation
        if any(
            event.phase == "completed" and event.plan.backup_id == plan.backup_id
            for event in events
        ):
            raise ValueError("Windows Coding Arch backup expiry already completed")
        event = CodingWindowsArchBackupExpiryEventV1(
            revision=len(events) + 1,
            phase="confirmed",
            plan=plan,
            confirmation=confirmation,
        )
        self._append(events, staged, event)
        return confirmation

    def begin(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
        archive: CodingWindowsArchBackupArchiveSnapshotV1,
    ) -> CodingWindowsArchBackupExpiryEventV1:
        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or confirmation.plan_fingerprint != plan.fingerprint
            or not isinstance(archive, CodingWindowsArchBackupArchiveSnapshotV1)
            or archive.root_identity != plan.archive_root_identity
            or archive.target_id != plan.archive_target_id
        ):
            raise ValueError("Windows Coding Arch backup expiry start is invalid")
        current = CodingWindowsArchPrivateDataBackupExpiryPreview(
            self.layout, self.product
        )._preview_locked(
            self.restore,
            plan.installation_key,
            plan.backup_id,
            plan.confirmation_id,
        )
        if current != plan:
            raise ValueError("Windows Coding Arch backup expiry plan changed")
        events, staged = self._scan()
        if not events or (
            events[-1].plan != plan or events[-1].confirmation != confirmation
        ):
            raise ValueError("Windows Coding Arch backup expiry confirmation changed")
        prior = events[-1]
        if prior.phase != "confirmed":
            if staged is not None or prior.archive != archive:
                raise ValueError("Windows Coding Arch backup expiry archive changed")
            return prior
        event = CodingWindowsArchBackupExpiryEventV1(
            revision=len(events) + 1,
            phase="started",
            plan=plan,
            confirmation=confirmation,
            archive=archive,
        )
        return self._append(events, staged, event)

    def advance(
        self,
        prior: CodingWindowsArchBackupExpiryEventV1,
        phase: Literal["renamed", "completed"],
    ) -> CodingWindowsArchBackupExpiryEventV1:
        if not isinstance(prior, CodingWindowsArchBackupExpiryEventV1) or phase not in {
            "renamed",
            "completed",
        }:
            raise ValueError("Windows Coding Arch backup expiry transition is invalid")
        events, staged = self._scan()
        if not events or events[-1] != prior:
            raise ValueError("Windows Coding Arch backup expiry checkpoint changed")
        if prior.phase == phase:
            if staged is not None:
                raise ValueError(
                    "Windows Coding Arch backup expiry event needs recovery"
                )
            return prior
        if (phase == "renamed" and prior.phase != "started") or (
            phase == "completed" and prior.phase != "renamed"
        ):
            raise ValueError(
                "Windows Coding Arch backup expiry checkpoint is out of order"
            )
        event = CodingWindowsArchBackupExpiryEventV1(
            revision=len(events) + 1,
            phase=phase,
            plan=prior.plan,
            confirmation=prior.confirmation,
            archive=prior.archive,
            receipt=(
                CodingArchPrivateDataBackupExpiryReceiptV1.create(
                    prior.plan, prior.confirmation
                )
                if phase == "completed"
                else None
            ),
        )
        return self._append(events, staged, event)

    def _append(
        self,
        before: tuple[CodingWindowsArchBackupExpiryEventV1, ...],
        staged: int | None,
        event: CodingWindowsArchBackupExpiryEventV1,
    ) -> CodingWindowsArchBackupExpiryEventV1:
        self.restore._require_active()
        if len(before) >= _MAX_EVENTS or staged not in {None, event.revision}:
            raise ValueError("Windows Coding Arch backup expiry event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > _MAX_EVENT_BYTES:
            raise ValueError("Windows Coding Arch backup expiry event is too large")
        write_windows_private_receipt(
            self._event_path(event.revision), payload, maximum_bytes=_MAX_EVENT_BYTES
        )
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError("Windows Coding Arch backup expiry event changed")
        return event

    def _scan(
        self,
    ) -> tuple[tuple[CodingWindowsArchBackupExpiryEventV1, ...], int | None]:
        self.restore._require_active()
        published: set[int] = set()
        staged: set[int] = set()
        for name in windows_listdir_at(self.restore.state_fd):
            if not name.startswith(_EVENT_PREFIX):
                continue
            match = _EVENT_NAME.fullmatch(name)
            if match is None:
                raise ValueError(
                    "Windows Coding Arch backup expiry member is unexpected"
                )
            revision = int(match.group(1))
            if revision < 1:
                raise ValueError("Windows Coding Arch backup expiry revision changed")
            (staged if match.group(2) else published).add(revision)
        if (
            len(published) > _MAX_EVENTS
            or len(staged) > 1
            or published != set(range(1, len(published) + 1))
            or (staged and staged != {len(published) + 1})
        ):
            raise ValueError("Windows Coding Arch backup expiry sequence changed")
        events: list[CodingWindowsArchBackupExpiryEventV1] = []
        for revision in range(1, len(published) + 1):
            raw = read_windows_private_receipt(
                self._event_path(revision), maximum_bytes=_MAX_EVENT_BYTES
            )
            if raw is None:
                raise ValueError("Windows Coding Arch backup expiry event disappeared")
            try:
                document = json.loads(
                    raw.decode("utf-8"), object_pairs_hook=_unique_object
                )
                event = CodingWindowsArchBackupExpiryEventV1.from_dict(document)
            except (TypeError, UnicodeError, ValueError) as exc:
                raise ValueError(
                    "Windows Coding Arch backup expiry event is invalid"
                ) from exc
            if (
                event.revision != revision
                or raw != canonical_json_bytes(event.to_dict()) + b"\n"
            ):
                raise ValueError("Windows Coding Arch backup expiry event changed")
            events.append(event)
        _validate_sequence(tuple(events))
        return tuple(events), next(iter(staged)) if staged else None

    def _event_path(self, revision: int) -> Path:
        return self.product.state_root / f"{_EVENT_PREFIX}{revision:08d}.json"


def _validate_sequence(
    events: tuple[CodingWindowsArchBackupExpiryEventV1, ...],
) -> None:
    previous: CodingWindowsArchBackupExpiryEventV1 | None = None
    completed: set[str] = set()
    for revision, event in enumerate(events, start=1):
        if event.revision != revision:
            raise ValueError("Windows Coding Arch backup expiry revision changed")
        if event.phase == "confirmed":
            if previous is not None and previous.phase != "completed":
                raise ValueError("Windows Coding Arch backup expiry history overlaps")
            if event.plan.backup_id in completed:
                raise ValueError("Windows Coding Arch backup expiry was repeated")
        elif (
            previous is None
            or previous.plan != event.plan
            or previous.confirmation != event.confirmation
            or (event.phase == "started" and previous.phase != "confirmed")
            or (event.phase == "renamed" and previous.phase != "started")
            or (event.phase == "completed" and previous.phase != "renamed")
            or (
                event.phase in {"renamed", "completed"}
                and previous.archive != event.archive
            )
        ):
            raise ValueError("Windows Coding Arch backup expiry history changed")
        if event.phase == "completed":
            completed.add(event.plan.backup_id)
        previous = event


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Windows Coding Arch backup expiry repeats a field")
        result[key] = value
    return result


__all__ = [
    "CodingWindowsArchBackupExpiryEventV1",
    "CodingWindowsArchBackupExpiryJournal",
    "CodingWindowsArchBackupExpiryTransaction",
]
