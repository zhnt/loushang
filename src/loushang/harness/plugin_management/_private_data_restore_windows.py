"""Fixed Windows restore receipts in the existing Plugin Management owner.

Product keeps admission, immutable record identity and root-generation policy.
Native receipt/tree/ACL operations reuse their original owners; no new store.
"""

from __future__ import annotations

import os
from dataclasses import Field, replace
from pathlib import Path
from re import Pattern
from typing import ClassVar, Generic, Literal, Protocol, Self, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._record_sequence import scan_numbered_revisions
from loushang.harness.journal.codec import decode_json_record
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
    private_windows_directory,
)
from loushang.harness.resources.packages._tree_observation import (
    logical_tree_members,
    metadata_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_flush_directory,
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from .private_data_deletion import PrivateDataDeletionTarget
from .private_data_restore_journal import (
    PrivateDataRestoreConfirmation,
    PrivateDataRestoreEvent,
    validate_restore_history,
)
from .records import PluginInstallationKeyV1


class _RestorePlan(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Field[object]]]

    @property
    def installation_key(self) -> PluginInstallationKeyV1: ...
    @property
    def backup_id(self) -> str: ...
    @property
    def deletion_receipt_id(self) -> str: ...
    @property
    def source_target_id(self) -> str: ...
    @property
    def desired_inventory_revision(self) -> int: ...
    @property
    def target_state(self) -> Literal["absent", "same_bytes"]: ...
    @property
    def fingerprint(self) -> str: ...


class _RestoreEvent(PrivateDataRestoreEvent, Protocol):
    @property
    def record_digest(self) -> str: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> Self: ...


class _RestoreConfirmation(PrivateDataRestoreConfirmation, Protocol):
    @property
    def confirmation_id(self) -> str: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> Self: ...
    @classmethod
    def create(
        cls,
        *,
        revision: int,
        installation_key: PluginInstallationKeyV1,
        backup_id: str,
        deletion_receipt_id: str,
        restore_id: str,
        restore_completion_digest: str,
        restored_target_id: str,
    ) -> Self: ...


class _RestorePublication(Protocol):
    def __init__(
        self,
        restore_id: str,
        started_digest: str,
        plan_fingerprint: str,
        desired_inventory_revision: int,
        generation_number: int,
        stage_identity: tuple[int, int, int, int, int],
        parent_identity: tuple[int, int],
    ) -> None: ...
    @property
    def restore_id(self) -> str: ...
    @property
    def started_digest(self) -> str: ...
    @property
    def plan_fingerprint(self) -> str: ...
    @property
    def desired_inventory_revision(self) -> int: ...
    @property
    def generation_number(self) -> int: ...
    @property
    def stage_identity(self) -> tuple[int, int, int, int, int]: ...
    @property
    def parent_identity(self) -> tuple[int, int]: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> Self: ...
    @property
    def stage_name(self) -> str: ...


_PlanT = TypeVar("_PlanT", bound=_RestorePlan)
_EventT = TypeVar("_EventT", bound=_RestoreEvent)
_ConfirmationT = TypeVar("_ConfirmationT", bound=_RestoreConfirmation)
_SourceT = TypeVar("_SourceT", bound=PrivateDataDeletionTarget)
_PublicationT = TypeVar("_PublicationT", bound=_RestorePublication)


class WindowsPrivateRestoreTransaction(
    Generic[_PlanT, _EventT, _ConfirmationT, _SourceT, _PublicationT]
):
    """Concrete two-phase restore; original Product scope owns the borrowed FD."""

    __slots__ = ()
    state_fd: int
    _active: bool
    _label: ClassVar[str]
    _event_prefix: ClassVar[str]
    _event_name: ClassVar[Pattern[str]]
    _publication_prefix: ClassVar[str]
    _confirmation_prefix: ClassVar[str]
    _confirmation_name: ClassVar[Pattern[str]]
    _restore_stage_prefix: ClassVar[str]
    _restore_stage_suffix: ClassVar[str]
    _max_events: ClassVar[int]
    _max_event_bytes: ClassVar[int]
    _publication_max_bytes: ClassVar[int]
    _confirmation_max_bytes: ClassVar[int]
    _writer_max_bytes: ClassVar[int]
    _receipt_io: ClassVar[WindowsPrivateReceiptIO]
    _tree_io: ClassVar[PrivateWindowsTreeIO]

    @property
    def _state_root(self) -> Path:
        raise NotImplementedError

    @property
    def _plan_type(self) -> type[_PlanT]:
        raise NotImplementedError

    @property
    def _event_type(self) -> type[_EventT]:
        raise NotImplementedError

    @property
    def _confirmation_type(self) -> type[_ConfirmationT]:
        raise NotImplementedError

    @property
    def _source_type(self) -> type[_SourceT]:
        raise NotImplementedError

    @property
    def _publication_type(self) -> type[_PublicationT]:
        raise NotImplementedError

    def _root_for(self, key: PluginInstallationKeyV1) -> Path:
        raise NotImplementedError

    def _inspect_bound_root(
        self, key: PluginInstallationKeyV1
    ) -> tuple[int, int] | None:
        raise NotImplementedError

    def _capture_root(self, root: Path, *, expected_root: tuple[int, int]) -> _SourceT:
        raise NotImplementedError

    def _require_plan_current(self, plan: _PlanT) -> _SourceT:
        raise NotImplementedError

    def _close(self) -> None:
        object.__setattr__(self, "_active", False)

    def _require_active(self) -> None:
        if not self._active:
            raise ValueError(f"{self._label} restore transaction is closed")

    def events(self) -> tuple[_EventT, ...]:
        events, staged = self._scan()
        if staged is not None:
            raise ValueError(f"{self._label} restore event needs recovery")
        return events

    def current_start(self) -> _EventT | None:
        events = self.events()
        return events[-1] if events and events[-1].phase == "started" else None

    def completed_plan_revision_for(self, plan: _PlanT) -> int:
        """Recover the original Product revision bound to one completed restore."""

        events = self.events()
        starts = tuple(
            (index, event)
            for index, event in enumerate(events)
            if event.phase == "started" and _same_plan(event, plan)
        )
        if len(starts) != 1:
            raise ValueError(f"{self._label} completed restore is unavailable")
        index, started = starts[0]
        if (
            index + 1 >= len(events)
            or events[index + 1].phase != "completed"
            or events[index + 1].restore_id != started.restore_id
        ):
            raise ValueError(f"{self._label} restore is unfinished")
        publication = self._read_publication(started, recover_stage=False)
        if publication is None:
            raise ValueError(f"{self._label} restore publication is missing")
        original = replace(
            plan,
            desired_inventory_revision=publication.desired_inventory_revision,
        )
        if publication.plan_fingerprint != original.fingerprint:
            raise ValueError(
                f"{self._label} restore publication changed: plan_fingerprint"
            )
        return publication.desired_inventory_revision

    def publication_for(
        self,
        started: _EventT,
        plan: _PlanT,
        *,
        recover_stage: bool = False,
    ) -> _PublicationT | None:
        self._require_active()
        if started.phase != "started" or not _same_plan(started, plan):
            raise ValueError(f"{self._label} restore publication is foreign")
        publication = self._read_publication(started, recover_stage=recover_stage)
        if publication is None:
            return None
        if (
            publication.plan_fingerprint != plan.fingerprint
            or publication.desired_inventory_revision != plan.desired_inventory_revision
        ):
            raise ValueError(
                f"{self._label} restore publication changed: plan_fingerprint"
            )
        return publication

    def _read_publication(
        self,
        started: _EventT,
        *,
        recover_stage: bool,
    ) -> _PublicationT | None:
        raw = self._receipt_io.read_private_receipt(
            self._publication_path(started),
            maximum_bytes=self._publication_max_bytes,
            allow_unpublished_stage=recover_stage,
        )
        if raw is None:
            return None
        publication = decode_json_record(
            raw,
            self._publication_type.from_dict,
            label=f"{self._label} restore publication",
            duplicate_message=f"{self._label} restore event has duplicate fields",
        )
        if raw != canonical_json_bytes(publication.to_dict()) + b"\n":
            reason = "bytes"
        elif publication.restore_id != started.restore_id:
            reason = "restore_id"
        elif publication.started_digest != started.record_digest:
            reason = "started_digest"
        else:
            reason = None
        if reason is not None:
            raise ValueError(f"{self._label} restore publication changed: {reason}")
        return publication

    def prepare_publication(
        self,
        started: _EventT,
        plan: _PlanT,
        source: _SourceT,
        generation_number: int,
        stage_identity: tuple[int, int, int, int, int],
    ) -> _PublicationT:
        """Persist stage identity before the no-replace rename to the target."""

        if (
            self._require_plan_current(plan) != source
            or self.current_start() != started
        ):
            raise ValueError(f"{self._label} restore start changed")
        root = self._root_for(plan.installation_key)
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"{self._label} restore root is already present")
        publication = self._publication_type(
            restore_id=started.restore_id,
            started_digest=started.record_digest,
            plan_fingerprint=plan.fingerprint,
            desired_inventory_revision=plan.desired_inventory_revision,
            generation_number=generation_number,
            stage_identity=stage_identity,
            parent_identity=inspect_windows_product_private_directory_identity(
                root.parent
            ),
        )
        staged = self._capture_root(
            root.parent / publication.stage_name,
            expected_root=stage_identity[:2],
        )
        if (
            staged.root_identity != stage_identity
            or logical_tree_members(staged) != logical_tree_members(source)
            or inspect_windows_product_private_directory_identity(root.parent)
            != publication.parent_identity
        ):
            raise ValueError(f"{self._label} restore stage changed")
        prior = self.publication_for(started, plan, recover_stage=True)
        if prior is not None:
            if prior != publication:
                raise ValueError(f"{self._label} restore publication changed")
            return prior
        payload = canonical_json_bytes(publication.to_dict()) + b"\n"
        if len(payload) > self._publication_max_bytes:
            raise ValueError(f"{self._label} restore publication is too large")
        try:
            self._receipt_io.write_private_receipt(
                self._publication_path(started),
                payload,
                maximum_bytes=self._writer_max_bytes,
            )
        except self._receipt_io.error_type:
            if self.publication_for(started, plan) != publication:
                raise
        if self.publication_for(started, plan) != publication:
            raise ValueError(f"{self._label} restore publication changed")
        return publication

    def confirm_restore(self, plan: _PlanT) -> _ConfirmationT:
        """Independently confirm completed restore and current exact bytes."""

        completion, restored = self._completed_restore(plan)
        records, staged = self._scan_confirmations()
        prior = next(
            (
                item
                for item in reversed(records)
                if item.restore_id == completion.restore_id
            ),
            None,
        )
        confirmation = self._confirmation_type.create(
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
                raise ValueError(f"{self._label} restore confirmation changed")
            return prior
        if len(records) >= self._max_events or staged not in {
            None,
            confirmation.revision,
        }:
            raise ValueError(f"{self._label} restore confirmation needs recovery")
        payload = canonical_json_bytes(confirmation.to_dict()) + b"\n"
        if len(payload) > self._confirmation_max_bytes:
            raise ValueError(f"{self._label} restore confirmation is too large")
        self._receipt_io.write_private_receipt(
            self._confirmation_path(confirmation.revision),
            payload,
            maximum_bytes=self._writer_max_bytes,
        )
        after, debt = self._scan_confirmations()
        if after != (*records, confirmation) or debt is not None:
            raise ValueError(f"{self._label} restore confirmation changed")
        if self._completed_restore(plan) != (completion, restored):
            raise ValueError(f"{self._label} restored bytes changed")
        return confirmation

    def verify_confirmation(self, plan: _PlanT, confirmation_id: str) -> _ConfirmationT:
        completion, restored = self._completed_restore(plan)
        records, staged = self._scan_confirmations()
        if staged is not None:
            raise ValueError(f"{self._label} restore confirmation needs recovery")
        match = next(
            (
                item
                for item in reversed(records)
                if item.confirmation_id == confirmation_id
            ),
            None,
        )
        expected = self._confirmation_type.create(
            revision=match.revision if match is not None else 1,
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
            restore_id=completion.restore_id,
            restore_completion_digest=completion.record_digest,
            restored_target_id=restored.target_id,
        )
        if match != expected:
            raise ValueError(f"{self._label} restore confirmation is stale")
        return match

    def _completed_restore(
        self, plan: _PlanT
    ) -> tuple[
        _EventT,
        _SourceT,
    ]:
        source = self._require_plan_current(plan)
        events = self.events()
        if (
            not events
            or events[-1].phase != "completed"
            or not _same_plan(events[-1], plan)
        ):
            raise ValueError(f"{self._label} restore is not completed")
        completion = events[-1]
        started = next(
            (
                event
                for event in reversed(events[:-1])
                if event.phase == "started"
                and event.restore_id == completion.restore_id
            ),
            None,
        )
        if started is None:
            raise ValueError(f"{self._label} restore start is missing")
        publication = self.publication_for(started, plan)
        if publication is None:
            raise ValueError(f"{self._label} restore publication is missing")
        root = self._root_for(plan.installation_key)
        parent_identity = inspect_windows_product_private_directory_identity(
            root.parent
        )
        if parent_identity != publication.parent_identity:
            raise ValueError(f"{self._label} restore parent changed")
        with private_windows_directory(root.parent) as parent_fd:
            if self._tree_io.directory_identity(parent_fd) != parent_identity:
                raise ValueError(f"{self._label} restore parent changed")
            names = set(windows_listdir_at(parent_fd))
            if root.name not in names or any(
                name.startswith(self._restore_stage_prefix) for name in names
            ):
                raise ValueError(f"{self._label} restore has stage debt")
        if (
            self._inspect_bound_root(plan.installation_key)
            != publication.stage_identity[:2]
        ):
            raise ValueError(f"{self._label} restored root binding changed")
        restored = self._capture_root(
            root, expected_root=publication.stage_identity[:2]
        )
        if restored.root_identity != publication.stage_identity or logical_tree_members(
            restored
        ) != logical_tree_members(source):
            raise ValueError(f"{self._label} restored bytes changed")
        return completion, restored

    def begin(self, plan: _PlanT) -> _EventT:
        if not isinstance(plan, self._plan_type) or plan.target_state != "absent":
            raise ValueError(f"{self._label} restore plan is invalid")
        self._root_for(plan.installation_key)
        self._require_plan_current(plan)
        events, staged = self._scan()
        if any(
            event.installation_key == plan.installation_key
            and event.deletion_receipt_id == plan.deletion_receipt_id
            and event.backup_id != plan.backup_id
            for event in events
        ):
            raise ValueError(f"{self._label} deletion has another restore")
        pending = events[-1] if events and events[-1].phase == "started" else None
        if pending is not None and not _same_plan(pending, plan):
            raise ValueError(f"Another {self._label} restore is unfinished")
        existing = next(
            (event for event in reversed(events) if _same_plan(event, plan)), None
        )
        if existing is not None:
            if staged is not None and existing.phase != "started":
                raise ValueError(f"{self._label} restore event needs recovery")
            return existing
        event = self._event_type.create(
            revision=len(events) + 1,
            phase="started",
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
        )
        return self._append(events, staged, event)

    def complete(
        self,
        started: _EventT,
        plan: _PlanT,
        source: _SourceT,
    ) -> _EventT:
        if (
            not isinstance(started, self._event_type)
            or started.phase != "started"
            or not isinstance(plan, self._plan_type)
            or not isinstance(source, self._source_type)
            or source.target_id != plan.source_target_id
            or plan.target_state != "absent"
            or not _same_plan(started, plan)
        ):
            raise ValueError(f"{self._label} restore completion is foreign")
        if self._require_plan_current(plan) != source:
            raise ValueError(f"{self._label} restore archive changed")
        events, staged = self._scan()
        replay = bool(
            events and events[-1].phase == "completed" and _same_plan(events[-1], plan)
        )
        if (replay and staged is not None) or (
            not replay and (not events or events[-1] != started)
        ):
            raise ValueError(f"{self._label} restore start changed")
        root = self._root_for(plan.installation_key)
        identity = self._inspect_bound_root(plan.installation_key)
        if identity is None:
            raise ValueError(f"{self._label} restored root is absent")
        restored = self._capture_root(root, expected_root=identity)
        if logical_tree_members(restored) != logical_tree_members(source):
            raise ValueError(f"{self._label} restored bytes changed")
        if replay:
            return events[-1]
        event = self._event_type.create(
            revision=len(events) + 1,
            phase="completed",
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            deletion_receipt_id=plan.deletion_receipt_id,
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
            raise ValueError(f"{self._label} restore event needs recovery")
        payload = canonical_json_bytes(event.to_dict()) + b"\n"
        if len(payload) > self._max_event_bytes:
            raise ValueError(f"{self._label} restore event is too large")
        self._receipt_io.write_private_receipt(
            self._event_path(event.revision),
            payload,
            maximum_bytes=self._writer_max_bytes,
        )
        after, debt = self._scan()
        if after != (*before, event) or debt is not None:
            raise ValueError(f"{self._label} restore event changed")
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
            unexpected_member=f"{self._label} restore member is unexpected",
            invalid_revision=f"{self._label} restore revision is invalid",
            invalid_sequence=f"{self._label} restore event sequence is invalid",
        )
        events: list[_EventT] = []
        for revision in range(1, published_count + 1):
            raw = self._receipt_io.read_private_receipt(
                self._event_path(revision), maximum_bytes=self._max_event_bytes
            )
            if raw is None:
                raise ValueError(f"{self._label} restore event disappeared")
            event = decode_windows_restore_event(
                raw, self._event_type, label=self._label
            )
            if event.revision != revision:
                raise ValueError(f"{self._label} restore revision changed")
            events.append(event)
        validate_windows_restore_sequence(tuple(events), label=self._label)
        return tuple(events), staged_revision

    def _event_path(self, revision: int) -> Path:
        return self._state_root / f"{self._event_prefix}{revision:08d}.json"

    def _publication_path(self, started: _EventT) -> Path:
        return (
            self._state_root
            / f"{self._publication_prefix}{started.restore_id.split(':', 1)[1]}.json"
        )

    def _confirmation_path(self, revision: int) -> Path:
        return self._state_root / f"{self._confirmation_prefix}{revision:08d}.json"

    def _scan_confirmations(
        self,
    ) -> tuple[tuple[_ConfirmationT, ...], int | None]:
        self._require_active()
        published_count, staged_revision = scan_numbered_revisions(
            windows_listdir_at(self.state_fd),
            prefix=self._confirmation_prefix,
            pattern=self._confirmation_name,
            max_records=self._max_events,
            unexpected_member=f"{self._label} restore confirmation member is unexpected",
            invalid_revision=f"{self._label} restore confirmation revision is invalid",
            invalid_sequence=f"{self._label} restore confirmation sequence changed",
        )
        records: list[_ConfirmationT] = []
        seen: set[str] = set()
        for revision in range(1, published_count + 1):
            raw = self._receipt_io.read_private_receipt(
                self._confirmation_path(revision),
                maximum_bytes=self._confirmation_max_bytes,
            )
            if raw is None:
                raise ValueError(f"{self._label} restore confirmation disappeared")
            record = decode_json_record(
                raw,
                self._confirmation_type.from_dict,
                label=f"{self._label} restore confirmation",
                duplicate_message=f"{self._label} restore event has duplicate fields",
            )
            if (
                record.revision != revision
                or record.restore_id in seen
                or raw != canonical_json_bytes(record.to_dict()) + b"\n"
            ):
                raise ValueError(f"{self._label} restore confirmation changed")
            seen.add(record.restore_id)
            records.append(record)
        return tuple(records), staged_revision

    def execute_restore(
        self, plan: _PlanT
    ) -> tuple[Literal["restored", "already_present"], str]:
        source = self._require_plan_current(plan)
        current = self.begin(plan)
        if current.phase == "completed":
            started = next(
                (
                    event
                    for event in reversed(self.events())
                    if event.phase == "started"
                    and event.restore_id == current.restore_id
                ),
                None,
            )
            if started is None:
                raise ValueError(f"{self._label} restore start is missing")
            publication = self.publication_for(started, plan)
            if publication is None:
                raise ValueError(f"{self._label} restore publication is missing")
            self._require_published_root(plan, source, publication)
            self.complete(started, plan, source)
            disposition: Literal["restored", "already_present"] = "already_present"
        else:
            self._restore_started(current, plan, source)
            self.complete(current, plan, source)
            disposition = "restored"
        return disposition, current.restore_id

    def _restore_started(
        self, started: _EventT, plan: _PlanT, source: _SourceT
    ) -> None:
        root = self._root_for(plan.installation_key)
        parent_identity = inspect_windows_product_private_directory_identity(
            root.parent
        )
        stage_name = (
            self._restore_stage_prefix
            + started.restore_id.split(":", 1)[1]
            + self._restore_stage_suffix
        )
        with WindowsPrivateDirectoryAcl() as exact_acl:
            with closing_descriptor(
                open_windows_directory(
                    root.parent, share_delete=False, read_control=True
                )
            ) as parent_fd:
                exact_acl.validate(parent_fd)
                if self._tree_io.directory_identity(parent_fd) != parent_identity:
                    raise ValueError(f"{self._label} restore parent changed")
                names = set(windows_listdir_at(parent_fd))
                if any(
                    name.startswith(self._restore_stage_prefix) and name != stage_name
                    for name in names
                ):
                    raise ValueError(f"Another {self._label} restore stage exists")
                publication = self.publication_for(started, plan, recover_stage=True)
                if root.name in names:
                    if publication is None or stage_name in names:
                        raise ValueError(f"{self._label} restore root is unclaimed")
                    self._require_published_root(plan, source, publication)
                else:
                    if publication is None:
                        if stage_name not in names:
                            stage_fd = self._tree_io.open_or_create_directory(
                                parent_fd, stage_name, exact_acl
                            )
                        else:
                            stage_fd = open_windows_directory(
                                stage_name,
                                dir_fd=parent_fd,
                                share_delete=False,
                                read_control=True,
                            )
                        try:
                            exact_acl.validate(stage_fd)
                            self._copy_archive_to_stage(plan, source, stage_fd)
                            stage_identity = metadata_identity(os.fstat(stage_fd))
                            staged = self._capture_root(
                                root.parent / stage_name,
                                expected_root=stage_identity[:2],
                            )
                            if (
                                staged.root_identity != stage_identity
                                or logical_tree_members(staged)
                                != logical_tree_members(source)
                            ):
                                raise ValueError(f"{self._label} restore stage changed")
                            windows_flush_directory(stage_fd)
                        finally:
                            os.close(stage_fd)
                        generation = self._prepare_root_generation(plan)
                        publication = self.prepare_publication(
                            started, plan, source, generation, stage_identity
                        )
                    elif stage_name not in names:
                        raise ValueError(f"{self._label} restore stage disappeared")
                    if publication.parent_identity != parent_identity:
                        raise ValueError(f"{self._label} restore parent changed")
                    self._tree_io.publish_restore_stage(
                        parent_fd,
                        root,
                        source,
                        publication.stage_name,
                        publication.stage_identity,
                        exact_acl,
                        capture=lambda path: self._capture_root(
                            path, expected_root=publication.stage_identity[:2]
                        ),
                    )
                    self._require_published_root(plan, source, publication)
                self._publish_root_generation(plan, publication)
                if self._tree_io.directory_identity(
                    parent_fd
                ) != parent_identity or stage_name in windows_listdir_at(parent_fd):
                    raise ValueError(f"{self._label} restore parent changed")

    def _require_published_root(
        self, plan: _PlanT, source: _SourceT, publication: _PublicationT
    ) -> None:
        root = self._root_for(plan.installation_key)
        if (
            publication.plan_fingerprint != plan.fingerprint
            or inspect_windows_product_private_directory_identity(root.parent)
            != publication.parent_identity
        ):
            raise ValueError(f"{self._label} restore publication changed")
        self._tree_io.require_restore_published_view(
            root,
            source,
            publication.stage_identity,
            stage_prefix=self._restore_stage_prefix,
            capture=lambda path: self._capture_root(
                path, expected_root=publication.stage_identity[:2]
            ),
        )

    def _prepare_root_generation(self, plan: _PlanT) -> int:
        raise NotImplementedError

    def _publish_root_generation(
        self, plan: _PlanT, publication: _PublicationT
    ) -> None:
        raise NotImplementedError

    def _copy_archive_to_stage(
        self, plan: _PlanT, source: _SourceT, stage_fd: int
    ) -> None:
        raise NotImplementedError


def decode_windows_restore_event(
    raw: bytes, event_type: type[_EventT], *, label: str
) -> _EventT:
    event = decode_json_record(
        raw,
        event_type.from_dict,
        label=f"{label} restore event",
    )
    if raw != canonical_json_bytes(event.to_dict()) + b"\n":
        raise ValueError(f"{label} restore event is noncanonical")
    return event


def validate_windows_restore_sequence(
    events: tuple[_EventT, ...],
    *,
    label: str,
) -> None:
    validate_restore_history(
        events,
        bind_deletion_backup=True,
        revision_error=f"{label} restore revision changed",
        starts_error=f"{label} restore starts conflict",
        completion_error=f"{label} restore completion has no start",
    )


def _same_plan(
    event: _EventT,
    plan: _PlanT,
) -> bool:
    return (
        event.installation_key == plan.installation_key
        and event.backup_id == plan.backup_id
        and event.deletion_receipt_id == plan.deletion_receipt_id
    )
