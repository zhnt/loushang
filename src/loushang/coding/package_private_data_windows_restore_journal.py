"""Native Product-private start/completion receipts for Windows Arch restore.

The journal records recovery state under one offline Product gate. It never
publishes archive bytes or creates a private-data root by itself.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

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
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_private_data_backup_records import backup_parent
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)
from .package_private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .package_private_data_windows_backup import (
    _directory_identity,
    _logical_members,
    _read_archive_manifest,
    _verify_archive,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
)

_EVENT_PREFIX = "arch-private-restore-"
_EVENT_NAME = re.compile(r"arch-private-restore-([0-9]{8})\.json(\.stage)?\Z")
_MAX_EVENTS = 4096
_MAX_EVENT_BYTES = 16 * 1024
_PUBLICATION_PREFIX = "arch-restore-publication-"
_PUBLICATION_MAX_BYTES = 4096
_CONFIRM_PREFIX = "arch-restore-confirmation-"
_CONFIRM_NAME = re.compile(r"arch-restore-confirmation-([0-9]{8})\.json(\.stage)?\Z")
_CONFIRM_MAX_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchRestorePublicationV1:
    restore_id: str
    started_digest: str
    plan_fingerprint: str
    generation_number: int
    stage_identity: tuple[int, int, int, int, int]
    parent_identity: tuple[int, int]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.restore_id, str)
            or not re.fullmatch(r"arch-restore:[0-9a-f]{64}", self.restore_id)
            or not isinstance(self.started_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.started_digest)
            or not isinstance(self.plan_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.plan_fingerprint)
            or type(self.generation_number) is not int
            or not 2 <= self.generation_number <= 4097
            or type(self.stage_identity) is not tuple
            or len(self.stage_identity) != 5
            or any(type(value) is not int or value < 0 for value in self.stage_identity)
            or type(self.parent_identity) is not tuple
            or len(self.parent_identity) != 2
            or any(type(value) is not int or value < 0 for value in self.parent_identity)
        ):
            raise ValueError("Windows Coding Arch restore publication is invalid")

    @property
    def stage_name(self) -> str:
        return ".arch-restore-" + self.restore_id.split(":", 1)[1] + ".staging"

    def to_dict(self) -> dict[str, object]:
        return {
            "generationNumber": self.generation_number,
            "parentIdentity": list(self.parent_identity),
            "planFingerprint": self.plan_fingerprint,
            "restoreId": self.restore_id,
            "stageIdentity": list(self.stage_identity),
            "startedDigest": self.started_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsArchRestorePublicationV1:
        if type(value) is not dict or set(value) != {
            "generationNumber", "parentIdentity", "planFingerprint", "restoreId",
            "stageIdentity", "startedDigest"
        }:
            raise ValueError("Windows Coding Arch restore publication fields changed")
        parent = value["parentIdentity"]
        stage = value["stageIdentity"]
        if type(parent) is not list or type(stage) is not list:
            raise ValueError("Windows Coding Arch restore publication identity changed")
        return cls(
            restore_id=value["restoreId"],
            started_digest=value["startedDigest"],
            plan_fingerprint=value["planFingerprint"],
            generation_number=value["generationNumber"],
            stage_identity=tuple(stage),
            parent_identity=tuple(parent),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        if (
            self.product.state_root
            != resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        ):
            raise ValueError("Windows Coding Arch restore Product state changed")

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchPrivateDataRestoreTransaction]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Windows Coding Arch restore runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard():
                with (
                    self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd
                ):
                    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
                        self.layout, self.product, fd
                    )
                    try:
                        yield transaction
                    finally:
                        transaction._close()
            self.product.assert_root_gc_authority_current()


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreTransaction:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner
    state_fd: int
    _active: bool = field(default=True, init=False, repr=False, compare=False)

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)

    def _require_active(self) -> None:
        if not self._active:
            raise ValueError("Windows Coding Arch restore transaction is closed")

    def events(self) -> tuple[CodingArchPrivateDataRestoreEventV1, ...]:
        events, staged = self._scan()
        if staged is not None:
            raise ValueError("Windows Coding Arch restore event needs recovery")
        return events

    def current_start(self) -> CodingArchPrivateDataRestoreEventV1 | None:
        events = self.events()
        return events[-1] if events and events[-1].phase == "started" else None

    def publication_for(
        self,
        started: CodingArchPrivateDataRestoreEventV1,
        plan: CodingArchPrivateDataRestorePlanV1,
        *,
        recover_stage: bool = False,
    ) -> CodingWindowsArchRestorePublicationV1 | None:
        self._require_active()
        if started.phase != "started" or not _same_plan(started, plan):
            raise ValueError("Windows Coding Arch restore publication is foreign")
        raw = read_windows_private_receipt(
            self._publication_path(started),
            maximum_bytes=_PUBLICATION_MAX_BYTES,
            allow_unpublished_stage=recover_stage,
        )
        if raw is None:
            return None
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            publication = CodingWindowsArchRestorePublicationV1.from_dict(document)
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Coding Arch restore publication is invalid") from exc
        if raw != canonical_json_bytes(publication.to_dict()) + b"\n":
            reason = "bytes"
        elif publication.restore_id != started.restore_id:
            reason = "restore_id"
        elif publication.started_digest != started.record_digest:
            reason = "started_digest"
        elif publication.plan_fingerprint != plan.fingerprint:
            reason = "plan_fingerprint"
        else:
            reason = None
        if reason is not None:
            raise ValueError(f"Windows Coding Arch restore publication changed: {reason}")
        return publication

    def prepare_publication(
        self,
        started: CodingArchPrivateDataRestoreEventV1,
        plan: CodingArchPrivateDataRestorePlanV1,
        source: CodingArchPrivateDataTargetSnapshotV1,
        generation_number: int,
        stage_identity: tuple[int, int, int, int, int],
    ) -> CodingWindowsArchRestorePublicationV1:
        """Persist stage identity before the no-replace rename to the target."""

        if self._require_plan_current(plan) != source or self.current_start() != started:
            raise ValueError("Windows Coding Arch restore start changed")
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Windows Coding Arch restore root is already present")
        publication = CodingWindowsArchRestorePublicationV1(
            restore_id=started.restore_id,
            started_digest=started.record_digest,
            plan_fingerprint=plan.fingerprint,
            generation_number=generation_number,
            stage_identity=stage_identity,
            parent_identity=inspect_windows_product_private_directory_identity(root.parent),
        )
        staged = _capture_windows_target_snapshot(
            root.parent / publication.stage_name,
            expected_root=stage_identity[:2],
        )
        if (
            staged.root_identity != stage_identity
            or _logical_members(staged) != _logical_members(source)
            or inspect_windows_product_private_directory_identity(root.parent)
            != publication.parent_identity
        ):
            raise ValueError("Windows Coding Arch restore stage changed")
        prior = self.publication_for(started, plan, recover_stage=True)
        if prior is not None:
            if prior != publication:
                raise ValueError("Windows Coding Arch restore publication changed")
            return prior
        payload = canonical_json_bytes(publication.to_dict()) + b"\n"
        if len(payload) > _PUBLICATION_MAX_BYTES:
            raise ValueError("Windows Coding Arch restore publication is too large")
        try:
            write_windows_private_receipt(self._publication_path(started), payload)
        except CodingWindowsPrivateReceiptError:
            if self.publication_for(started, plan) != publication:
                raise
        if self.publication_for(started, plan) != publication:
            raise ValueError("Windows Coding Arch restore publication changed")
        return publication

    def confirm_restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Independently confirm completed restore and current exact bytes."""

        completion, restored = self._completed_restore(plan)
        records, staged = self._scan_confirmations()
        prior = next(
            (item for item in reversed(records) if item.restore_id == completion.restore_id),
            None,
        )
        confirmation = CodingArchPrivateDataRestoreConfirmationV1.create(
            revision=prior.revision if prior is not None else len(records) + 1,
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
            restore_id=completion.restore_id,
            restore_completion_digest=completion.record_digest,
            restored_target_id=restored.target_id,
        )
        if prior is not None:
            if staged is not None or prior != confirmation:
                raise ValueError("Windows Coding Arch restore confirmation changed")
            return prior
        if len(records) >= _MAX_EVENTS or staged not in {None, confirmation.revision}:
            raise ValueError("Windows Coding Arch restore confirmation needs recovery")
        payload = canonical_json_bytes(confirmation.to_dict()) + b"\n"
        if len(payload) > _CONFIRM_MAX_BYTES:
            raise ValueError("Windows Coding Arch restore confirmation is too large")
        write_windows_private_receipt(
            self._confirmation_path(confirmation.revision), payload
        )
        after, debt = self._scan_confirmations()
        if after != (*records, confirmation) or debt is not None:
            raise ValueError("Windows Coding Arch restore confirmation changed")
        if self._completed_restore(plan) != (completion, restored):
            raise ValueError("Windows Coding Arch restored bytes changed")
        return confirmation

    def verify_confirmation(
        self, plan: CodingArchPrivateDataRestorePlanV1, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        completion, restored = self._completed_restore(plan)
        records, staged = self._scan_confirmations()
        if staged is not None:
            raise ValueError("Windows Coding Arch restore confirmation needs recovery")
        match = next(
            (item for item in reversed(records) if item.confirmation_id == confirmation_id),
            None,
        )
        expected = CodingArchPrivateDataRestoreConfirmationV1.create(
            revision=match.revision if match is not None else 1,
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
            restore_id=completion.restore_id,
            restore_completion_digest=completion.record_digest,
            restored_target_id=restored.target_id,
        )
        if match != expected:
            raise ValueError("Windows Coding Arch restore confirmation is stale")
        return match

    def _completed_restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> tuple[
        CodingArchPrivateDataRestoreEventV1,
        CodingArchPrivateDataTargetSnapshotV1,
    ]:
        source = self._require_plan_current(plan)
        events = self.events()
        if not events or events[-1].phase != "completed" or not _same_plan(
            events[-1], plan
        ):
            raise ValueError("Windows Coding Arch restore is not completed")
        completion = events[-1]
        started = next(
            (
                event
                for event in reversed(events[:-1])
                if event.phase == "started" and event.restore_id == completion.restore_id
            ),
            None,
        )
        if started is None:
            raise ValueError("Windows Coding Arch restore start is missing")
        publication = self.publication_for(started, plan)
        if publication is None:
            raise ValueError("Windows Coding Arch restore publication is missing")
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        parent_identity = inspect_windows_product_private_directory_identity(root.parent)
        if parent_identity != publication.parent_identity:
            raise ValueError("Windows Coding Arch restore parent changed")
        with WindowsPrivateDirectoryAcl() as acl:
            parent_fd = open_windows_directory(
                root.parent, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if _directory_identity(parent_fd) != parent_identity:
                    raise ValueError("Windows Coding Arch restore parent changed")
                names = set(windows_listdir_at(parent_fd))
                if root.name not in names or any(
                    name.startswith(".arch-restore-") for name in names
                ):
                    raise ValueError("Windows Coding Arch restore has stage debt")
            finally:
                os.close(parent_fd)
        if (
            inspect_coding_windows_arch_installation_root(
                self.layout, plan.installation_key, state_root=self.product.state_root
            )
            != publication.stage_identity[:2]
        ):
            raise ValueError("Windows Coding Arch restored root binding changed")
        restored = _capture_windows_target_snapshot(
            root, expected_root=publication.stage_identity[:2]
        )
        if (
            restored.root_identity != publication.stage_identity
            or _logical_members(restored) != _logical_members(source)
        ):
            raise ValueError("Windows Coding Arch restored bytes changed")
        return completion, restored

    def begin(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreEventV1:
        if (
            not isinstance(plan, CodingArchPrivateDataRestorePlanV1)
            or plan.target_state != "absent"
        ):
            raise ValueError("Windows Coding Arch restore plan is invalid")
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        self._require_plan_current(plan)
        events, staged = self._scan()
        if any(
            event.installation_key == plan.installation_key
            and event.deletion_receipt_id == plan.deletion_receipt_id
            and event.backup_id != plan.backup_id
            for event in events
        ):
            raise ValueError("Windows Coding Arch deletion has another restore")
        pending = events[-1] if events and events[-1].phase == "started" else None
        if pending is not None and not _same_plan(pending, plan):
            raise ValueError("Another Windows Coding Arch restore is unfinished")
        existing = next(
            (event for event in reversed(events) if _same_plan(event, plan)), None
        )
        if existing is not None:
            if staged is not None and existing.phase != "started":
                raise ValueError("Windows Coding Arch restore event needs recovery")
            return existing
        event = CodingArchPrivateDataRestoreEventV1.create(
            revision=len(events) + 1,
            phase="started",
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
        )
        return self._append(events, staged, event)

    def complete(
        self,
        started: CodingArchPrivateDataRestoreEventV1,
        plan: CodingArchPrivateDataRestorePlanV1,
        source: CodingArchPrivateDataTargetSnapshotV1,
    ) -> CodingArchPrivateDataRestoreEventV1:
        if (
            not isinstance(started, CodingArchPrivateDataRestoreEventV1)
            or started.phase != "started"
            or not isinstance(plan, CodingArchPrivateDataRestorePlanV1)
            or not isinstance(source, CodingArchPrivateDataTargetSnapshotV1)
            or source.target_id != plan.source_target_id
            or plan.target_state != "absent"
            or not _same_plan(started, plan)
        ):
            raise ValueError("Windows Coding Arch restore completion is foreign")
        if self._require_plan_current(plan) != source:
            raise ValueError("Windows Coding Arch restore archive changed")
        events, staged = self._scan()
        replay = bool(
            events and events[-1].phase == "completed" and _same_plan(events[-1], plan)
        )
        if (replay and staged is not None) or (
            not replay and (not events or events[-1] != started)
        ):
            raise ValueError("Windows Coding Arch restore start changed")
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        identity = inspect_coding_windows_arch_installation_root(
            self.layout, plan.installation_key, state_root=self.product.state_root
        )
        if identity is None:
            raise ValueError("Windows Coding Arch restored root is absent")
        restored = _capture_windows_target_snapshot(root, expected_root=identity)
        if _logical_members(restored) != _logical_members(source):
            raise ValueError("Windows Coding Arch restored bytes changed")
        if replay:
            return events[-1]
        event = CodingArchPrivateDataRestoreEventV1.create(
            revision=len(events) + 1,
            phase="completed",
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
        )
        return self._append(events, staged, event)

    def _require_plan_current(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        desired, transitions = self.product.desired_state.capture()
        state = desired.installation(plan.installation_key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
            or desired.inventory_revision < plan.desired_inventory_revision
            or any(
                transition.inventory_revision > plan.desired_inventory_revision
                and transition.mutation.installation_key == plan.installation_key
                for transition in transitions
            )
        ):
            raise ValueError("Windows Coding Arch restore Product state changed")
        deletion = CodingWindowsArchPrivateDataDeletionTransaction(
            self.product.state_root, self.state_fd
        )
        try:
            events = deletion.events()
        finally:
            deletion._close()
        if events and events[-1].phase != "completed":
            raise ValueError("Windows Coding Arch deletion is unfinished")
        receipt = _latest_deletion_receipt(events, plan)
        if receipt != plan.deletion_receipt_id:
            raise ValueError("Windows Coding Arch restore deletion changed")
        return self._verify_plan_archive(plan)

    def _verify_plan_archive(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        parent_path = backup_parent(self.layout, plan.installation_key)
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        with WindowsPrivateDirectoryAcl() as acl:
            parent_fd = open_windows_directory(
                parent_path, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if _directory_identity(parent_fd) != parent_identity or any(
                    name.endswith(".staging") for name in windows_listdir_at(parent_fd)
                ):
                    raise ValueError("Windows Coding Arch backup parent changed")
                receipt, source = _read_archive_manifest(parent_fd, plan.backup_id, acl)
                if (
                    receipt.installation_key != plan.installation_key
                    or receipt.backup_id != plan.backup_id
                    or source.target_id != plan.source_target_id
                ):
                    raise ValueError("Windows Coding Arch restore archive changed")
                _verify_archive(
                    parent_fd,
                    parent_path,
                    plan.backup_id,
                    plan.installation_key,
                    source,
                    receipt,
                    acl,
                )
                return source
            finally:
                os.close(parent_fd)
                if (
                    inspect_windows_product_private_directory_identity(parent_path)
                    != parent_identity
                ):
                    raise ValueError("Windows Coding Arch backup parent changed")

    def _append(
        self,
        before: tuple[CodingArchPrivateDataRestoreEventV1, ...],
        staged: int | None,
        event: CodingArchPrivateDataRestoreEventV1,
    ) -> CodingArchPrivateDataRestoreEventV1:
        self._require_active()
        if len(before) >= _MAX_EVENTS or staged not in {None, event.revision}:
            raise ValueError("Windows Coding Arch restore event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > _MAX_EVENT_BYTES:
            raise ValueError("Windows Coding Arch restore event is too large")
        write_windows_private_receipt(self._event_path(event.revision), payload)
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError("Windows Coding Arch restore event changed")
        return event

    def _scan(
        self,
    ) -> tuple[tuple[CodingArchPrivateDataRestoreEventV1, ...], int | None]:
        self._require_active()
        published: set[int] = set()
        staged: set[int] = set()
        for name in windows_listdir_at(self.state_fd):
            if not name.startswith(_EVENT_PREFIX):
                continue
            match = _EVENT_NAME.fullmatch(name)
            if match is None:
                raise ValueError("Windows Coding Arch restore member is unexpected")
            revision = int(match.group(1))
            if revision < 1:
                raise ValueError("Windows Coding Arch restore revision is invalid")
            (staged if match.group(2) else published).add(revision)
        if (
            len(published) > _MAX_EVENTS
            or len(staged) > 1
            or published != set(range(1, len(published) + 1))
            or (staged and staged != {len(published) + 1})
        ):
            raise ValueError("Windows Coding Arch restore event sequence is invalid")
        events: list[CodingArchPrivateDataRestoreEventV1] = []
        for revision in range(1, len(published) + 1):
            raw = read_windows_private_receipt(
                self._event_path(revision), maximum_bytes=_MAX_EVENT_BYTES
            )
            if raw is None:
                raise ValueError("Windows Coding Arch restore event disappeared")
            event = _decode_event(raw)
            if event.revision != revision:
                raise ValueError("Windows Coding Arch restore revision changed")
            events.append(event)
        _validate_sequence(tuple(events))
        return tuple(events), next(iter(staged)) if staged else None

    def _event_path(self, revision: int) -> Path:
        return self.product.state_root / f"{_EVENT_PREFIX}{revision:08d}.json"

    def _publication_path(self, started: CodingArchPrivateDataRestoreEventV1) -> Path:
        return (
            self.product.state_root
            / f"{_PUBLICATION_PREFIX}{started.restore_id.split(':', 1)[1]}.json"
        )

    def _confirmation_path(self, revision: int) -> Path:
        return self.product.state_root / f"{_CONFIRM_PREFIX}{revision:08d}.json"

    def _scan_confirmations(
        self,
    ) -> tuple[tuple[CodingArchPrivateDataRestoreConfirmationV1, ...], int | None]:
        self._require_active()
        published: set[int] = set()
        staged: set[int] = set()
        for name in windows_listdir_at(self.state_fd):
            if not name.startswith(_CONFIRM_PREFIX):
                continue
            match = _CONFIRM_NAME.fullmatch(name)
            if match is None:
                raise ValueError("Windows Coding Arch restore confirmation member is unexpected")
            revision = int(match.group(1))
            if revision < 1:
                raise ValueError("Windows Coding Arch restore confirmation revision is invalid")
            (staged if match.group(2) else published).add(revision)
        if (
            len(published) > _MAX_EVENTS
            or len(staged) > 1
            or published != set(range(1, len(published) + 1))
            or (staged and staged != {len(published) + 1})
        ):
            raise ValueError("Windows Coding Arch restore confirmation sequence changed")
        records: list[CodingArchPrivateDataRestoreConfirmationV1] = []
        seen: set[str] = set()
        for revision in range(1, len(published) + 1):
            raw = read_windows_private_receipt(
                self._confirmation_path(revision), maximum_bytes=_CONFIRM_MAX_BYTES
            )
            if raw is None:
                raise ValueError("Windows Coding Arch restore confirmation disappeared")
            try:
                document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
                record = CodingArchPrivateDataRestoreConfirmationV1.from_dict(document)
            except (TypeError, UnicodeError, ValueError) as exc:
                raise ValueError("Windows Coding Arch restore confirmation is invalid") from exc
            if (
                record.revision != revision
                or record.restore_id in seen
                or raw != canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError("Windows Coding Arch restore confirmation changed")
            seen.add(record.restore_id)
            records.append(record)
        return tuple(records), next(iter(staged)) if staged else None


def _latest_deletion_receipt(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
    plan: CodingArchPrivateDataRestorePlanV1,
) -> str | None:
    for event in reversed(events):
        if event.plan.installation_key != plan.installation_key:
            continue
        if (
            event.phase == "completed"
            and event.target.target_id == plan.source_target_id
            and event.receipt is not None
            and event.receipt.disposition == "deleted"
        ):
            return event.receipt.receipt_id
        return None
    return None


def _decode_event(raw: bytes) -> CodingArchPrivateDataRestoreEventV1:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        event = CodingArchPrivateDataRestoreEventV1.from_dict(document)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("Windows Coding Arch restore event is invalid") from exc
    if raw != canonical_json_bytes(event.to_dict()) + b"\n":
        raise ValueError("Windows Coding Arch restore event is noncanonical")
    return event


def _validate_sequence(
    events: tuple[CodingArchPrivateDataRestoreEventV1, ...],
) -> None:
    pending: CodingArchPrivateDataRestoreEventV1 | None = None
    seen: set[str] = set()
    consumed: dict[tuple[object, str], str] = {}
    for revision, event in enumerate(events, start=1):
        if event.revision != revision:
            raise ValueError("Windows Coding Arch restore revision changed")
        if event.phase == "started":
            prior_backup = consumed.get(
                (event.installation_key, event.deletion_receipt_id)
            )
            if (
                pending is not None
                or event.restore_id in seen
                or (prior_backup is not None and prior_backup != event.backup_id)
            ):
                raise ValueError("Windows Coding Arch restore starts conflict")
            pending = event
            seen.add(event.restore_id)
            consumed[(event.installation_key, event.deletion_receipt_id)] = (
                event.backup_id
            )
        elif (
            pending is None
            or event.restore_id != pending.restore_id
            or event.installation_key != pending.installation_key
            or event.backup_id != pending.backup_id
            or event.deletion_receipt_id != pending.deletion_receipt_id
        ):
            raise ValueError("Windows Coding Arch restore completion has no start")
        else:
            pending = None


def _same_plan(
    event: CodingArchPrivateDataRestoreEventV1,
    plan: CodingArchPrivateDataRestorePlanV1,
) -> bool:
    return (
        event.installation_key == plan.installation_key
        and event.backup_id == plan.backup_id
        and event.deletion_receipt_id == plan.deletion_receipt_id
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Windows Coding Arch restore event has duplicate fields")
        result[key] = value
    return result


__all__ = [
    "CodingWindowsArchPrivateDataRestoreJournal",
    "CodingWindowsArchPrivateDataRestoreTransaction",
]
