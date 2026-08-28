from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRuntimeEventV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeError,
    PluginInstanceRuntimeInventorySnapshotV1,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.package_records import (
    PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC,
    PluginCleanupAttemptV1,
    PluginCleanupRepairDecisionV1,
    PluginCleanupTaskV1,
    PluginPackageLifecycleEventV1,
    PluginPackagePinKind,
    PluginPackagePinReleaseV1,
    PluginPackagePinV1,
    PluginPackageRecoveryBarrierV1,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import PluginRetirementError
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetError,
    PluginRetirementSetInventorySnapshotV1,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_PACKAGE_GC_CANDIDATE_VERSION = 1

PluginCleanupTaskState = Literal[
    "pending",
    "retryable_failure",
    "terminal_failure",
    "retry_permitted",
    "succeeded",
    "safe_abandoned",
]


class PluginPackageDesiredStateSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]: ...


class PluginPackageInstanceRuntimeSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginInstanceRuntimeInventorySnapshotV1: ...

    def events(self) -> tuple[PluginInstanceRuntimeEventV1, ...]: ...

    def release_family(
        self,
        release: PluginInstanceLeaseFamilyReleaseV1,
    ) -> PluginInstanceLeaseFamilyReleaseV1: ...


class PluginPackageRetirementSetSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginRetirementSetInventorySnapshotV1: ...


class PluginPackageLifecycleError(RuntimeError):
    """Fail-closed package-lifecycle failure with one stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginCleanupTaskSnapshotV1:
    task: PluginCleanupTaskV1
    attempts: tuple[PluginCleanupAttemptV1, ...]
    repair_decisions: tuple[PluginCleanupRepairDecisionV1, ...]
    state: PluginCleanupTaskState

    def __post_init__(self) -> None:
        if any(attempt.cleanup_id != self.task.cleanup_id for attempt in self.attempts):
            raise ValueError("Plugin cleanup attempts do not match their task")
        if tuple(attempt.attempt for attempt in self.attempts) != tuple(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("Plugin cleanup attempts must be contiguous")
        if any(
            decision.cleanup_id != self.task.cleanup_id
            for decision in self.repair_decisions
        ):
            raise ValueError("Plugin cleanup repairs do not match their task")
        if tuple(
            decision.repair_sequence for decision in self.repair_decisions
        ) != tuple(range(1, len(self.repair_decisions) + 1)):
            raise ValueError("Plugin cleanup repairs must be contiguous")
        _validate_cleanup_evidence(self.attempts, self.repair_decisions)
        if self.state != _derive_cleanup_state(
            self.attempts,
            self.repair_decisions,
        ):
            raise ValueError("Plugin cleanup state does not match its evidence")

    @property
    def lease_open(self) -> bool:
        return self.state not in {"succeeded", "safe_abandoned"}


@dataclass(frozen=True, slots=True)
class PluginPackageGcCandidateV1:
    candidate_id: str
    package_revision: PluginPackageRevisionRefV1
    desired_inventory_revision: int
    instance_runtime_revision: int
    package_journal_revision: int
    recovery_barrier_id: str
    candidate_version: int = PLUGIN_PACKAGE_GC_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_id, name="Plugin Package GC candidate id")
        _require_sha256(
            self.recovery_barrier_id,
            name="Plugin Package recovery barrier id",
        )
        for revision, name in (
            (self.desired_inventory_revision, "desired inventory revision"),
            (self.instance_runtime_revision, "Instance runtime revision"),
            (self.package_journal_revision, "Package journal revision"),
        ):
            _require_nonnegative_integer(revision, name=name)
        if self.candidate_version != PLUGIN_PACKAGE_GC_CANDIDATE_VERSION:
            raise ValueError("Unsupported Plugin Package GC candidate version")
        if self.candidate_id != plugin_package_gc_candidate_id(
            package_revision=self.package_revision,
            desired_inventory_revision=self.desired_inventory_revision,
            instance_runtime_revision=self.instance_runtime_revision,
            package_journal_revision=self.package_journal_revision,
            recovery_barrier_id=self.recovery_barrier_id,
        ):
            raise ValueError("Plugin Package GC candidate id does not match")

    @classmethod
    def create(
        cls,
        *,
        package_revision: PluginPackageRevisionRefV1,
        desired_inventory_revision: int,
        instance_runtime_revision: int,
        package_journal_revision: int,
        recovery_barrier_id: str,
    ) -> PluginPackageGcCandidateV1:
        return cls(
            candidate_id=plugin_package_gc_candidate_id(
                package_revision=package_revision,
                desired_inventory_revision=desired_inventory_revision,
                instance_runtime_revision=instance_runtime_revision,
                package_journal_revision=package_journal_revision,
                recovery_barrier_id=recovery_barrier_id,
            ),
            package_revision=package_revision,
            desired_inventory_revision=desired_inventory_revision,
            instance_runtime_revision=instance_runtime_revision,
            package_journal_revision=package_journal_revision,
            recovery_barrier_id=recovery_barrier_id,
        )


@dataclass(frozen=True, slots=True)
class PluginPackageRetentionSnapshotV1:
    package_revision: PluginPackageRevisionRefV1
    desired_installations: tuple[PluginInstallationKeyV1, ...]
    nonretired_instances: tuple[PluginInstanceRevisionRef, ...]
    open_runtime_family_ids: tuple[str, ...]
    open_pin_ids: tuple[str, ...]
    open_cleanup_ids: tuple[str, ...]
    terminal_failure_cleanup_ids: tuple[str, ...]
    recovery_complete: bool
    gc_candidate: PluginPackageGcCandidateV1 | None

    def __post_init__(self) -> None:
        if self.desired_installations != tuple(sorted(self.desired_installations)) or len(
            self.desired_installations
        ) != len(set(self.desired_installations)):
            raise ValueError(
                "Plugin Package desired Installations must be sorted and unique"
            )
        if self.nonretired_instances != tuple(
            sorted(self.nonretired_instances, key=_instance_sort_key)
        ) or len(self.nonretired_instances) != len(set(self.nonretired_instances)):
            raise ValueError(
                "Plugin Package non-retired Instances must be sorted and unique"
            )
        for values, name in (
            (self.open_runtime_family_ids, "open runtime family ids"),
            (self.open_pin_ids, "open Package pin ids"),
            (self.open_cleanup_ids, "open cleanup ids"),
            (self.terminal_failure_cleanup_ids, "terminal-failure cleanup ids"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"Plugin Package {name} must be sorted and unique")
        if not set(self.terminal_failure_cleanup_ids).issubset(
            self.open_cleanup_ids
        ):
            raise ValueError("Terminal cleanup failure must retain its lease")
        blocked = any(
            (
                self.desired_installations,
                self.nonretired_instances,
                self.open_runtime_family_ids,
                self.open_pin_ids,
                self.open_cleanup_ids,
                self.terminal_failure_cleanup_ids,
            )
        )
        if (self.gc_candidate is not None) != (
            self.recovery_complete and not blocked
        ):
            raise ValueError("Plugin Package GC candidate contradicts retention")
        if (
            self.gc_candidate is not None
            and self.gc_candidate.package_revision != self.package_revision
        ):
            raise ValueError("Plugin Package GC candidate revision does not match")


@dataclass(frozen=True, slots=True)
class PluginPackageLifecycleSnapshotV1:
    journal_revision: int
    startup_id: str
    recovery_barrier: PluginPackageRecoveryBarrierV1 | None
    open_pins: tuple[PluginPackagePinV1, ...]
    cleanup_tasks: tuple[PluginCleanupTaskSnapshotV1, ...]
    packages: tuple[PluginPackageRetentionSnapshotV1, ...]

    def __post_init__(self) -> None:
        _require_nonnegative_integer(
            self.journal_revision,
            name="Plugin Package journal revision",
        )
        _require_nonempty(self.startup_id, name="Plugin Package startup id")
        if (
            self.recovery_barrier is not None
            and self.recovery_barrier.startup_id != self.startup_id
        ):
            raise ValueError("Plugin Package recovery barrier startup does not match")
        if self.open_pins != tuple(sorted(self.open_pins, key=lambda item: item.pin_id)):
            raise ValueError("Open Plugin Package pins must be sorted")
        if len({item.pin_id for item in self.open_pins}) != len(self.open_pins):
            raise ValueError("Open Plugin Package pins must be unique")
        if self.cleanup_tasks != tuple(
            sorted(self.cleanup_tasks, key=lambda item: item.task.cleanup_id)
        ):
            raise ValueError("Plugin cleanup task snapshots must be sorted")
        if len({item.task.cleanup_id for item in self.cleanup_tasks}) != len(
            self.cleanup_tasks
        ):
            raise ValueError("Plugin cleanup task snapshots must be unique")
        if self.packages != tuple(
            sorted(self.packages, key=lambda item: _package_sort_key(item.package_revision))
        ):
            raise ValueError("Plugin Package retention snapshots must be sorted")
        if len({item.package_revision for item in self.packages}) != len(self.packages):
            raise ValueError("Plugin Package retention snapshots must be unique")

    @property
    def startup_recovered(self) -> bool:
        return self.recovery_barrier is not None

    def cleanup(self, cleanup_id: str) -> PluginCleanupTaskSnapshotV1 | None:
        for item in self.cleanup_tasks:
            if item.task.cleanup_id == cleanup_id:
                return item
        return None

    def package(
        self,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PluginPackageRetentionSnapshotV1 | None:
        for item in self.packages:
            if item.package_revision == package_revision:
                return item
        return None


@dataclass(slots=True)
class _MutablePin:
    pin: PluginPackagePinV1
    release: PluginPackagePinReleaseV1 | None


@dataclass(slots=True)
class _MutableCleanup:
    task: PluginCleanupTaskV1
    attempts: list[PluginCleanupAttemptV1]
    repair_decisions: list[PluginCleanupRepairDecisionV1]


@dataclass(slots=True)
class _ReplayedPackageLifecycle:
    events: list[PluginPackageLifecycleEventV1]
    pins: dict[str, _MutablePin]
    cleanups: dict[str, _MutableCleanup]
    source_family_cleanups: dict[str, str]
    barriers: dict[str, PluginPackageRecoveryBarrierV1]
    operation_events: dict[str, PluginPackageLifecycleEventV1]
    idempotency_events: dict[str, PluginPackageLifecycleEventV1]


@dataclass(frozen=True, slots=True)
class _SourceEvidence:
    desired_snapshot: PluginDesiredStateSnapshotV1
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...]
    runtime_snapshot: PluginInstanceRuntimeInventorySnapshotV1
    runtime_events: tuple[PluginInstanceRuntimeEventV1, ...]
    retirement_sets: PluginRetirementSetInventorySnapshotV1


class PluginPackageLifecycleLedger:
    """Durable cleanup leases and conservative Package Revision retention."""

    def __init__(
        self,
        path: str | Path,
        *,
        startup_id: str,
        desired_state: PluginPackageDesiredStateSourcePort,
        instance_runtime: PluginPackageInstanceRuntimeSourcePort,
        retirement_sets: PluginPackageRetirementSetSourcePort,
    ) -> None:
        self._path = Path(path)
        _require_nonempty(startup_id, name="Plugin Package startup id")
        self._startup_id = startup_id
        self._desired_state = desired_state
        self._instance_runtime = instance_runtime
        self._retirement_sets = retirement_sets
        paths = {
            self._path.resolve(),
            desired_state.path.resolve(),
            instance_runtime.path.resolve(),
            retirement_sets.path.resolve(),
        }
        if len(paths) != 4:
            raise ValueError("Plugin Package lifecycle journals must be distinct")
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def startup_id(self) -> str:
        return self._startup_id

    @property
    def instance_runtime_journal_path(self) -> Path:
        """Durable Instance authority backing every package cleanup handoff."""

        return self._instance_runtime.path

    def acquire_pin(
        self,
        package_revision: PluginPackageRevisionRefV1,
        *,
        pin_kind: PluginPackagePinKind,
        operation_id: str,
        idempotency_key: str,
        holder_reference: str,
    ) -> PluginPackagePinV1:
        if not isinstance(package_revision, PluginPackageRevisionRefV1):
            raise TypeError("Plugin Package Revision is required")
        pin = PluginPackagePinV1.create(
            package_revision=package_revision,
            pin_kind=pin_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            holder_reference=holder_reference,
        )
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            repeated = self._existing_operation(replayed, pin)
            if repeated is not None:
                if repeated.pin != pin:
                    raise _conflict(self._path, "Plugin Package pin identity was reused")
                mutable = replayed.pins[pin.pin_id]
                if mutable.release is not None:
                    raise _transition_error(
                        self._path,
                        "Plugin Package pin acquisition was already released",
                    )
                return pin
            if pin.pin_id in replayed.pins:
                raise _conflict(self._path, "Plugin Package pin id was reused")
            self._append_and_apply_unlocked(replayed, pin)
            return pin

    def release_pin(
        self,
        release: PluginPackagePinReleaseV1,
    ) -> PluginPackagePinReleaseV1:
        if not isinstance(release, PluginPackagePinReleaseV1):
            raise TypeError("Plugin Package pin release is required")
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            repeated = self._existing_operation(replayed, release)
            if repeated is not None:
                if repeated.pin_release != release:
                    raise _conflict(
                        self._path,
                        "Plugin Package pin release identity was reused",
                    )
                return release
            mutable = replayed.pins.get(release.pin_id)
            if mutable is None:
                raise _transition_error(self._path, "Plugin Package pin is unknown")
            if mutable.release is not None:
                raise _conflict(
                    self._path,
                    "Plugin Package pin has different release evidence",
                )
            self._append_and_apply_unlocked(replayed, release)
            return release

    def handoff_cleanup_and_release(
        self,
        source_family_id: str,
        *,
        retirement_target_id: str | None,
        cleanup_kind: str,
        operation_id: str,
        idempotency_key: str,
        cleanup_reference: str,
        family_release: PluginInstanceLeaseFamilyReleaseV1,
    ) -> PluginCleanupTaskV1:
        _require_sha256(source_family_id, name="cleanup source family id")
        if not isinstance(family_release, PluginInstanceLeaseFamilyReleaseV1):
            raise TypeError("Plugin Instance family release is required")
        if family_release.family_id != source_family_id:
            raise ValueError("Cleanup handoff and family release must match")
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            repeated = self._existing_operation_keys(
                replayed,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            if repeated is not None:
                task = repeated.cleanup_task
                if (
                    task is None
                    or task.source_family.family_id != source_family_id
                    or task.retirement_target_id != retirement_target_id
                    or task.cleanup_kind != cleanup_kind
                    or task.cleanup_reference != cleanup_reference
                ):
                    raise _conflict(
                        self._path,
                        "Plugin cleanup handoff identity was reused",
                    )
                self._instance_runtime.release_family(family_release)
                return task
        family = sources.runtime_snapshot.family(source_family_id)
        if family is None or family.lease_kind not in {
            "direct_host",
            "owner_generation",
        }:
            raise _transition_error(
                self._path,
                "Cleanup handoff requires an open host/owner family",
            )
        member = family.members[0]
        instance = sources.runtime_snapshot.instance(member.instance_revision_ref)
        if instance is None:
            raise _corrupt(self._path, "Cleanup source Instance is absent")
        if instance.state == "DRAINING":
            intent = instance.retirement_intent
            if intent is None:
                raise _corrupt(self._path, "DRAINING Instance lacks retirement intent")
            coordination_kind: Literal["graceful", "security"] = "graceful"
            coordination_id = intent.retirement_id
        elif instance.state == "REVOKING":
            revocation = instance.revocation
            if revocation is None:
                raise _corrupt(self._path, "REVOKING Instance lacks revocation")
            coordination_kind = "security"
            coordination_id = revocation.revocation_id
        else:
            raise _transition_error(
                self._path,
                "Cleanup handoff requires DRAINING or REVOKING Instance",
            )
        try:
            task = PluginCleanupTaskV1.create(
                source_runtime_revision=sources.runtime_snapshot.journal_revision,
                source_family=family,
                coordination_kind=coordination_kind,
                coordination_id=coordination_id,
                retirement_target_id=retirement_target_id,
                cleanup_kind=cleanup_kind,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                cleanup_reference=cleanup_reference,
            )
        except ValueError as exc:
            raise _transition_error(
                self._path,
                "Plugin cleanup handoff evidence is invalid",
            ) from exc
        self._prepare_cleanup(task, sources=sources)
        self._instance_runtime.release_family(family_release)
        return task

    def record_cleanup_attempt(
        self,
        attempt: PluginCleanupAttemptV1,
    ) -> PluginCleanupTaskSnapshotV1:
        if not isinstance(attempt, PluginCleanupAttemptV1):
            raise TypeError("Plugin cleanup attempt is required")
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            repeated = self._existing_operation(replayed, attempt)
            if repeated is not None:
                if repeated.cleanup_attempt != attempt:
                    raise _conflict(
                        self._path,
                        "Plugin cleanup attempt identity was reused",
                    )
                return _snapshot_cleanup(replayed.cleanups[attempt.cleanup_id])
            current = replayed.cleanups.get(attempt.cleanup_id)
            if current is None:
                raise _transition_error(self._path, "Plugin cleanup task is unknown")
            expected_attempt = len(current.attempts) + 1
            if attempt.attempt != expected_attempt:
                raise _transition_error(
                    self._path,
                    "Plugin cleanup attempt is not contiguous",
                )
            if _derive_cleanup_state(
                tuple(current.attempts),
                tuple(current.repair_decisions),
            ) not in {"pending", "retryable_failure", "retry_permitted"}:
                raise _transition_error(
                    self._path,
                    "Plugin cleanup task cannot accept another attempt",
                )
            self._append_and_apply_unlocked(replayed, attempt)
            return _snapshot_cleanup(current)

    def record_repair_decision(
        self,
        decision: PluginCleanupRepairDecisionV1,
    ) -> PluginCleanupTaskSnapshotV1:
        if not isinstance(decision, PluginCleanupRepairDecisionV1):
            raise TypeError("Plugin cleanup repair decision is required")
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            repeated = self._existing_operation(replayed, decision)
            if repeated is not None:
                if repeated.repair_decision != decision:
                    raise _conflict(
                        self._path,
                        "Plugin cleanup repair identity was reused",
                    )
                return _snapshot_cleanup(replayed.cleanups[decision.cleanup_id])
            current = replayed.cleanups.get(decision.cleanup_id)
            if current is None:
                raise _transition_error(self._path, "Plugin cleanup task is unknown")
            if decision.repair_sequence != len(current.repair_decisions) + 1:
                raise _transition_error(
                    self._path,
                    "Plugin cleanup repair sequence is not contiguous",
                )
            if _derive_cleanup_state(
                tuple(current.attempts),
                tuple(current.repair_decisions),
            ) != "terminal_failure":
                raise _transition_error(
                    self._path,
                    "Plugin cleanup repair requires terminal failure",
                )
            self._append_and_apply_unlocked(replayed, decision)
            return _snapshot_cleanup(current)

    def complete_startup_recovery(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        recovery_reference: str,
    ) -> PluginPackageRecoveryBarrierV1:
        for value, name in (
            (operation_id, "Plugin Package recovery operation id"),
            (idempotency_key, "Plugin Package recovery idempotency key"),
            (recovery_reference, "Plugin Package recovery reference"),
        ):
            _require_nonempty(value, name=name)
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            repeated = self._existing_operation_keys(
                replayed,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            if repeated is not None:
                barrier = repeated.recovery_barrier
                if (
                    barrier is None
                    or barrier.startup_id != self._startup_id
                    or barrier.recovery_reference != recovery_reference
                ):
                    raise _conflict(
                        self._path,
                        "Plugin Package recovery identity was reused",
                    )
                return barrier
            if self._startup_id in replayed.barriers:
                raise _conflict(
                    self._path,
                    "Plugin Package startup already has a recovery barrier",
                )
            barrier = PluginPackageRecoveryBarrierV1.create(
                startup_id=self._startup_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                recovery_reference=recovery_reference,
                observed_desired_inventory_revision=(
                    sources.desired_snapshot.inventory_revision
                ),
                observed_instance_runtime_revision=(
                    sources.runtime_snapshot.journal_revision
                ),
                observed_package_journal_revision=len(replayed.events),
                open_pin_ids=tuple(
                    sorted(
                        pin_id
                        for pin_id, current in replayed.pins.items()
                        if current.release is None
                    )
                ),
                open_cleanup_ids=tuple(
                    sorted(
                        cleanup_id
                        for cleanup_id, current in replayed.cleanups.items()
                        if _snapshot_cleanup(current).lease_open
                    )
                ),
            )
            self._append_and_apply_unlocked(replayed, barrier)
            return barrier

    def snapshot(self) -> PluginPackageLifecycleSnapshotV1:
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            return _snapshot_lifecycle(
                replayed,
                sources=sources,
                startup_id=self._startup_id,
            )

    def gc_candidates(self) -> tuple[PluginPackageGcCandidateV1, ...]:
        snapshot = self.snapshot()
        if not snapshot.startup_recovered:
            raise PluginPackageLifecycleError(
                "Plugin Package startup recovery is incomplete",
                code="plugin_package_recovery_incomplete",
                path=self._path,
            )
        return tuple(
            item.gc_candidate
            for item in snapshot.packages
            if item.gc_candidate is not None
        )

    def recheck_gc_candidate(
        self,
        candidate: PluginPackageGcCandidateV1,
    ) -> PluginPackageGcCandidateV1:
        if not isinstance(candidate, PluginPackageGcCandidateV1):
            raise TypeError("Plugin Package GC candidate is required")
        for current in self.gc_candidates():
            if current.package_revision == candidate.package_revision:
                if current != candidate:
                    raise _transition_error(
                        self._path,
                        "Plugin Package GC candidate revisions are stale",
                    )
                return candidate
        raise _transition_error(
            self._path,
            "Plugin Package Revision is not currently GC-eligible",
        )

    def events(self) -> tuple[PluginPackageLifecycleEventV1, ...]:
        sources = self._load_sources()
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            return tuple(replayed.events)

    def _prepare_cleanup(
        self,
        task: PluginCleanupTaskV1,
        *,
        sources: _SourceEvidence,
    ) -> PluginCleanupTaskV1:
        with self._exclusive_lock():
            replayed = self._load_and_replay_unlocked()
            self._validate_sources(replayed, sources)
            self._validate_cleanup_source(task, sources=sources, replay=False)
            repeated = self._existing_operation(replayed, task)
            if repeated is not None:
                if repeated.cleanup_task != task:
                    raise _conflict(
                        self._path,
                        "Plugin cleanup task identity was reused",
                    )
                return task
            existing_id = replayed.source_family_cleanups.get(
                task.source_family.family_id
            )
            if existing_id is not None:
                raise _conflict(
                    self._path,
                    "Plugin cleanup source family already has a task",
                )
            self._append_and_apply_unlocked(replayed, task)
            return task

    def _load_sources(self) -> _SourceEvidence:
        try:
            desired_snapshot = self._desired_state.snapshot()
            desired_transitions = self._desired_state.transitions()
            runtime_snapshot = self._instance_runtime.snapshot()
            runtime_events = self._instance_runtime.events()
            retirement_sets = self._retirement_sets.snapshot()
        except (
            PluginInstanceRuntimeError,
            PluginLifecycleError,
            PluginRetirementError,
            PluginRetirementSetError,
        ) as exc:
            raise _corrupt(
                self._path,
                "Plugin Package lifecycle source cannot be reconstructed",
            ) from exc
        if desired_snapshot.inventory_revision != len(desired_transitions):
            raise _corrupt(
                self._path,
                "Desired-state snapshot and transitions are inconsistent",
            )
        if runtime_snapshot.journal_revision != len(runtime_events):
            raise _corrupt(
                self._path,
                "Instance runtime snapshot and events are inconsistent",
            )
        return _SourceEvidence(
            desired_snapshot=desired_snapshot,
            desired_transitions=desired_transitions,
            runtime_snapshot=runtime_snapshot,
            runtime_events=runtime_events,
            retirement_sets=retirement_sets,
        )

    def _validate_sources(
        self,
        replayed: _ReplayedPackageLifecycle,
        sources: _SourceEvidence,
    ) -> None:
        for current in replayed.cleanups.values():
            self._validate_cleanup_source(
                current.task,
                sources=sources,
                replay=True,
            )
        for barrier in replayed.barriers.values():
            if (
                barrier.observed_desired_inventory_revision
                > sources.desired_snapshot.inventory_revision
                or barrier.observed_instance_runtime_revision
                > sources.runtime_snapshot.journal_revision
            ):
                raise _corrupt(
                    self._path,
                    "Plugin Package recovery source history disappeared",
                )

    def _validate_cleanup_source(
        self,
        task: PluginCleanupTaskV1,
        *,
        sources: _SourceEvidence,
        replay: bool,
    ) -> None:
        fail = _corrupt if replay else _transition_error
        if task.source_runtime_revision > len(sources.runtime_events):
            raise fail(self._path, "Cleanup runtime source revision disappeared")
        source_events = sources.runtime_events[: task.source_runtime_revision]
        family = _family_from_events(
            source_events,
            family_id=task.source_family.family_id,
        )
        if family != task.source_family or _family_released(
            source_events,
            family_id=task.source_family.family_id,
        ):
            raise fail(
                self._path,
                "Plugin cleanup source family contradicts runtime history",
            )
        state, coordination_id = _instance_coordination_at(
            source_events,
            instance_revision_ref=task.instance_revision_ref,
        )
        if task.coordination_kind == "graceful":
            if state != "DRAINING" or coordination_id != task.coordination_id:
                raise fail(
                    self._path,
                    "Graceful cleanup coordination contradicts runtime history",
                )
            retirement_set = sources.retirement_sets.retirement_set(
                task.coordination_id
            )
            if retirement_set is None or retirement_set.plan is None:
                raise fail(
                    self._path,
                    "Graceful cleanup lacks a sealed retirement plan",
                )
            if task.source_family.lease_kind == "owner_generation":
                target = next(
                    (
                        target
                        for target in retirement_set.plan.targets
                        if target.target_id == task.retirement_target_id
                    ),
                    None,
                )
                if (
                    target is None
                    or target.owner_generation_reference
                    != task.source_family.holder_reference
                ):
                    raise fail(
                        self._path,
                        "Cleanup target does not match its owner generation",
                    )
        elif state != "REVOKING" or coordination_id != task.coordination_id:
            raise fail(
                self._path,
                "Security cleanup coordination contradicts runtime history",
            )

    def _load_and_replay_unlocked(self) -> _ReplayedPackageLifecycle:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginPackageLifecycleEventV1] = load_jsonl(
                self._path,
                record_codec=PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_package_lifecycle_record",
                    "unsupported_plugin_package_lifecycle_record_version",
                }
                else "plugin_package_lifecycle_journal_corrupt"
            )
            raise PluginPackageLifecycleError(
                "Plugin Package lifecycle journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        return _replay(snapshot.records, path=self._path)

    def _append_and_apply_unlocked(
        self,
        replayed: _ReplayedPackageLifecycle,
        payload: (
            PluginPackagePinV1
            | PluginPackagePinReleaseV1
            | PluginCleanupTaskV1
            | PluginCleanupAttemptV1
            | PluginCleanupRepairDecisionV1
            | PluginPackageRecoveryBarrierV1
        ),
    ) -> None:
        event = PluginPackageLifecycleEventV1.for_payload(
            journal_revision=len(replayed.events) + 1,
            payload=payload,
        )
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )
        _apply_event(replayed, event, path=self._path)

    def _existing_operation(
        self,
        replayed: _ReplayedPackageLifecycle,
        payload: object,
    ) -> PluginPackageLifecycleEventV1 | None:
        operation_id = getattr(payload, "operation_id")
        idempotency_key = getattr(payload, "idempotency_key")
        return self._existing_operation_keys(
            replayed,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
        )

    def _existing_operation_keys(
        self,
        replayed: _ReplayedPackageLifecycle,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PluginPackageLifecycleEventV1 | None:
        by_operation = replayed.operation_events.get(operation_id)
        by_idempotency = replayed.idempotency_events.get(idempotency_key)
        if by_operation is None and by_idempotency is None:
            return None
        if by_operation is None or by_idempotency is None:
            raise _conflict(
                self._path,
                "Plugin Package operation identity was partially reused",
            )
        if by_operation is not by_idempotency:
            raise _conflict(
                self._path,
                "Plugin Package operation and idempotency identities diverge",
            )
        return by_operation

    def _exclusive_lock(self):
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )


def _empty_replay() -> _ReplayedPackageLifecycle:
    return _ReplayedPackageLifecycle(
        events=[],
        pins={},
        cleanups={},
        source_family_cleanups={},
        barriers={},
        operation_events={},
        idempotency_events={},
    )


def _replay(
    events: tuple[PluginPackageLifecycleEventV1, ...],
    *,
    path: Path,
) -> _ReplayedPackageLifecycle:
    replayed = _empty_replay()
    for event in events:
        _apply_event(replayed, event, path=path)
    return replayed


def _apply_event(
    replayed: _ReplayedPackageLifecycle,
    event: PluginPackageLifecycleEventV1,
    *,
    path: Path,
) -> None:
    if event.journal_revision != len(replayed.events) + 1:
        raise _corrupt(path, "Plugin Package journal revision is not contiguous")
    operation_id, idempotency_key = _event_operation_identity(event)
    if operation_id in replayed.operation_events:
        raise _corrupt(path, "Plugin Package operation id is duplicated")
    if idempotency_key in replayed.idempotency_events:
        raise _corrupt(path, "Plugin Package idempotency key is duplicated")

    if event.pin is not None:
        if event.pin.pin_id in replayed.pins:
            raise _corrupt(path, "Plugin Package pin id is duplicated")
        replayed.pins[event.pin.pin_id] = _MutablePin(event.pin, None)
    elif event.pin_release is not None:
        current_pin = replayed.pins.get(event.pin_release.pin_id)
        if current_pin is None or current_pin.release is not None:
            raise _corrupt(path, "Plugin Package pin release is invalid")
        current_pin.release = event.pin_release
    elif event.cleanup_task is not None:
        task = event.cleanup_task
        if task.cleanup_id in replayed.cleanups:
            raise _corrupt(path, "Plugin cleanup id is duplicated")
        if task.source_family.family_id in replayed.source_family_cleanups:
            raise _corrupt(path, "Plugin cleanup source family is duplicated")
        replayed.cleanups[task.cleanup_id] = _MutableCleanup(task, [], [])
        replayed.source_family_cleanups[task.source_family.family_id] = task.cleanup_id
    elif event.cleanup_attempt is not None:
        attempt = event.cleanup_attempt
        current_cleanup = replayed.cleanups.get(attempt.cleanup_id)
        if current_cleanup is None:
            raise _corrupt(path, "Plugin cleanup attempt has no task")
        if attempt.attempt != len(current_cleanup.attempts) + 1:
            raise _corrupt(path, "Plugin cleanup attempt is not contiguous")
        state = _derive_cleanup_state(
            tuple(current_cleanup.attempts),
            tuple(current_cleanup.repair_decisions),
        )
        if state not in {"pending", "retryable_failure", "retry_permitted"}:
            raise _corrupt(path, "Plugin cleanup attempt transition is invalid")
        current_cleanup.attempts.append(attempt)
    elif event.repair_decision is not None:
        decision = event.repair_decision
        current_cleanup = replayed.cleanups.get(decision.cleanup_id)
        if current_cleanup is None:
            raise _corrupt(path, "Plugin cleanup repair has no task")
        if decision.repair_sequence != len(current_cleanup.repair_decisions) + 1:
            raise _corrupt(path, "Plugin cleanup repair is not contiguous")
        if _derive_cleanup_state(
            tuple(current_cleanup.attempts),
            tuple(current_cleanup.repair_decisions),
        ) != "terminal_failure":
            raise _corrupt(path, "Plugin cleanup repair transition is invalid")
        current_cleanup.repair_decisions.append(decision)
    else:
        barrier = event.recovery_barrier
        if barrier is None:
            raise _corrupt(path, "Plugin Package recovery barrier is missing")
        if barrier.startup_id in replayed.barriers:
            raise _corrupt(path, "Plugin Package startup barrier is duplicated")
        if barrier.observed_package_journal_revision != len(replayed.events):
            raise _corrupt(path, "Plugin Package recovery revision is inconsistent")
        if barrier.open_pin_ids != tuple(
            sorted(
                pin_id
                for pin_id, current in replayed.pins.items()
                if current.release is None
            )
        ):
            raise _corrupt(path, "Plugin Package recovery pin set is inconsistent")
        if barrier.open_cleanup_ids != tuple(
            sorted(
                cleanup_id
                for cleanup_id, current in replayed.cleanups.items()
                if _snapshot_cleanup(current).lease_open
            )
        ):
            raise _corrupt(path, "Plugin Package recovery cleanup set is inconsistent")
        replayed.barriers[barrier.startup_id] = barrier

    replayed.operation_events[operation_id] = event
    replayed.idempotency_events[idempotency_key] = event
    replayed.events.append(event)


def _event_operation_identity(
    event: PluginPackageLifecycleEventV1,
) -> tuple[str, str]:
    payload = next(
        item
        for item in (
            event.pin,
            event.pin_release,
            event.cleanup_task,
            event.cleanup_attempt,
            event.repair_decision,
            event.recovery_barrier,
        )
        if item is not None
    )
    return payload.operation_id, payload.idempotency_key


def _derive_cleanup_state(
    attempts: tuple[PluginCleanupAttemptV1, ...],
    repairs: tuple[PluginCleanupRepairDecisionV1, ...],
) -> PluginCleanupTaskState:
    if not attempts:
        return "pending"
    latest_attempt = attempts[-1]
    if latest_attempt.disposition == "succeeded":
        return "succeeded"
    if latest_attempt.disposition == "retryable_failure":
        return "retryable_failure"
    repairs_after_latest_terminal = len(repairs) - sum(
        1 for attempt in attempts[:-1] if attempt.disposition == "terminal_failure"
    )
    if repairs_after_latest_terminal == 0:
        return "terminal_failure"
    latest_repair = repairs[-1]
    return "retry_permitted" if latest_repair.action == "retry" else "safe_abandoned"


def _validate_cleanup_evidence(
    attempts: tuple[PluginCleanupAttemptV1, ...],
    repairs: tuple[PluginCleanupRepairDecisionV1, ...],
) -> None:
    terminal_attempts = tuple(
        attempt for attempt in attempts if attempt.disposition == "terminal_failure"
    )
    if len(repairs) > len(terminal_attempts):
        raise ValueError("Plugin cleanup repair has no terminal attempt")
    if any(
        attempt.disposition == "succeeded" for attempt in attempts[:-1]
    ):
        raise ValueError("Successful Plugin cleanup attempt must be final")
    for index, terminal_attempt in enumerate(terminal_attempts):
        has_later_attempt = terminal_attempt.attempt < len(attempts)
        repair = repairs[index] if index < len(repairs) else None
        if has_later_attempt and (repair is None or repair.action != "retry"):
            raise ValueError("Plugin cleanup retry lacks a repair decision")
        if repair is not None and repair.action == "safe_abandon" and (
            has_later_attempt or index != len(repairs) - 1
        ):
            raise ValueError("Safe-abandoned Plugin cleanup cannot continue")


def _snapshot_cleanup(current: _MutableCleanup) -> PluginCleanupTaskSnapshotV1:
    attempts = tuple(current.attempts)
    repairs = tuple(current.repair_decisions)
    return PluginCleanupTaskSnapshotV1(
        task=current.task,
        attempts=attempts,
        repair_decisions=repairs,
        state=_derive_cleanup_state(attempts, repairs),
    )


def _snapshot_lifecycle(
    replayed: _ReplayedPackageLifecycle,
    *,
    sources: _SourceEvidence,
    startup_id: str,
) -> PluginPackageLifecycleSnapshotV1:
    barrier = replayed.barriers.get(startup_id)
    open_pins = tuple(
        sorted(
            (
                current.pin
                for current in replayed.pins.values()
                if current.release is None
            ),
            key=lambda item: item.pin_id,
        )
    )
    cleanup_tasks = tuple(
        sorted(
            (_snapshot_cleanup(current) for current in replayed.cleanups.values()),
            key=lambda item: item.task.cleanup_id,
        )
    )
    known_packages = _known_packages(replayed, sources=sources)
    packages = tuple(
        _retention_snapshot(
            package_revision,
            replayed=replayed,
            sources=sources,
            startup_barrier=barrier,
        )
        for package_revision in sorted(known_packages, key=_package_sort_key)
    )
    return PluginPackageLifecycleSnapshotV1(
        journal_revision=len(replayed.events),
        startup_id=startup_id,
        recovery_barrier=barrier,
        open_pins=open_pins,
        cleanup_tasks=cleanup_tasks,
        packages=packages,
    )


def _known_packages(
    replayed: _ReplayedPackageLifecycle,
    *,
    sources: _SourceEvidence,
) -> set[PluginPackageRevisionRefV1]:
    packages: set[PluginPackageRevisionRefV1] = set()
    for transition in sources.desired_transitions:
        for state in (transition.previous_state, transition.committed_state):
            if state.selection.package_revision is not None:
                packages.add(state.selection.package_revision)
    for instance in sources.runtime_snapshot.instances:
        packages.add(instance.package_revision)
    packages.update(current.pin.package_revision for current in replayed.pins.values())
    packages.update(
        current.task.package_revision for current in replayed.cleanups.values()
    )
    return packages


def _retention_snapshot(
    package_revision: PluginPackageRevisionRefV1,
    *,
    replayed: _ReplayedPackageLifecycle,
    sources: _SourceEvidence,
    startup_barrier: PluginPackageRecoveryBarrierV1 | None,
) -> PluginPackageRetentionSnapshotV1:
    desired_installations = tuple(
        sorted(
            installation.installation_key
            for installation in sources.desired_snapshot.installations
            if installation.selection.package_revision == package_revision
        )
    )
    nonretired_instances = tuple(
        sorted(
            (
                instance.instance_revision_ref
                for instance in sources.runtime_snapshot.instances
                if instance.package_revision == package_revision
                and instance.state != "RETIRED"
            ),
            key=_instance_sort_key,
        )
    )
    open_runtime_family_ids = tuple(
        sorted(
            family.family_id
            for family in sources.runtime_snapshot.open_families
            if any(
                member.package_revision == package_revision
                for member in family.members
            )
        )
    )
    open_pin_ids = tuple(
        sorted(
            pin_id
            for pin_id, current in replayed.pins.items()
            if current.pin.package_revision == package_revision
            and current.release is None
        )
    )
    cleanup_snapshots = tuple(
        _snapshot_cleanup(current)
        for current in replayed.cleanups.values()
        if current.task.package_revision == package_revision
    )
    open_cleanup_ids = tuple(
        sorted(
            item.task.cleanup_id for item in cleanup_snapshots if item.lease_open
        )
    )
    terminal_failure_cleanup_ids = tuple(
        sorted(
            item.task.cleanup_id
            for item in cleanup_snapshots
            if item.state == "terminal_failure"
        )
    )
    blocked = any(
        (
            desired_installations,
            nonretired_instances,
            open_runtime_family_ids,
            open_pin_ids,
            open_cleanup_ids,
            terminal_failure_cleanup_ids,
        )
    )
    candidate = (
        None
        if startup_barrier is None or blocked
        else PluginPackageGcCandidateV1.create(
            package_revision=package_revision,
            desired_inventory_revision=sources.desired_snapshot.inventory_revision,
            instance_runtime_revision=sources.runtime_snapshot.journal_revision,
            package_journal_revision=len(replayed.events),
            recovery_barrier_id=startup_barrier.barrier_id,
        )
    )
    return PluginPackageRetentionSnapshotV1(
        package_revision=package_revision,
        desired_installations=desired_installations,
        nonretired_instances=nonretired_instances,
        open_runtime_family_ids=open_runtime_family_ids,
        open_pin_ids=open_pin_ids,
        open_cleanup_ids=open_cleanup_ids,
        terminal_failure_cleanup_ids=terminal_failure_cleanup_ids,
        recovery_complete=startup_barrier is not None,
        gc_candidate=candidate,
    )


def _family_from_events(
    events: tuple[PluginInstanceRuntimeEventV1, ...],
    *,
    family_id: str,
) -> PluginInstanceLeaseFamilyV1 | None:
    for event in events:
        if (
            event.activation is not None
            and event.activation.direct_host_family.family_id == family_id
        ):
            return event.activation.direct_host_family
        if event.family is not None and event.family.family_id == family_id:
            return event.family
    return None


def _family_released(
    events: tuple[PluginInstanceRuntimeEventV1, ...],
    *,
    family_id: str,
) -> bool:
    return any(
        event.release is not None and event.release.family_id == family_id
        for event in events
    )


def _instance_coordination_at(
    events: tuple[PluginInstanceRuntimeEventV1, ...],
    *,
    instance_revision_ref: PluginInstanceRevisionRef,
) -> tuple[str, str | None]:
    state = "ABSENT"
    coordination_id: str | None = None
    for event in events:
        if (
            event.activation is not None
            and event.activation.instance_revision_ref == instance_revision_ref
        ):
            state = "ACTIVE"
        elif (
            event.retirement_intent is not None
            and event.retirement_intent.instance_revision_ref
            == instance_revision_ref
        ):
            state = "DRAINING"
            coordination_id = event.retirement_intent.retirement_id
        elif (
            event.revocation is not None
            and event.revocation.instance_revision_ref == instance_revision_ref
        ):
            state = "REVOKING"
            coordination_id = event.revocation.revocation_id
        elif (
            event.completion is not None
            and event.completion.instance_revision_ref == instance_revision_ref
        ):
            state = "RETIRED"
    return state, coordination_id


def plugin_package_gc_candidate_id(
    *,
    package_revision: PluginPackageRevisionRefV1,
    desired_inventory_revision: int,
    instance_runtime_revision: int,
    package_journal_revision: int,
    recovery_barrier_id: str,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "desiredInventoryRevision": desired_inventory_revision,
            "instanceRuntimeRevision": instance_runtime_revision,
            "packageJournalRevision": package_journal_revision,
            "packageRevision": package_revision.to_dict(),
            "recoveryBarrierId": recovery_barrier_id,
        }
    )
    return sha256(b"plugin-package-gc-candidate-v1\0" + payload).hexdigest()


def _package_sort_key(
    package_revision: PluginPackageRevisionRefV1,
) -> tuple[str, str, str, str, str]:
    return (
        package_revision.plugin_id,
        package_revision.plugin_version or "",
        package_revision.package_content_digest,
        package_revision.dependency_lock_digest,
        package_revision.package_source_identity,
    )


def _instance_sort_key(
    instance_revision_ref: PluginInstanceRevisionRef,
) -> tuple[str, str, int]:
    return (
        instance_revision_ref.plugin_id,
        instance_revision_ref.instance_id,
        instance_revision_ref.revision,
    )


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_nonnegative_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _conflict(path: Path, message: str) -> PluginPackageLifecycleError:
    return PluginPackageLifecycleError(
        message,
        code="plugin_package_lifecycle_conflict",
        path=path,
    )


def _transition_error(path: Path, message: str) -> PluginPackageLifecycleError:
    return PluginPackageLifecycleError(
        message,
        code="invalid_plugin_package_lifecycle_transition",
        path=path,
    )


def _corrupt(path: Path, message: str) -> PluginPackageLifecycleError:
    return PluginPackageLifecycleError(
        message,
        code="plugin_package_lifecycle_journal_corrupt",
        path=path,
    )


__all__ = [
    "PLUGIN_PACKAGE_GC_CANDIDATE_VERSION",
    "PluginCleanupTaskSnapshotV1",
    "PluginCleanupTaskState",
    "PluginPackageDesiredStateSourcePort",
    "PluginPackageGcCandidateV1",
    "PluginPackageInstanceRuntimeSourcePort",
    "PluginPackageLifecycleError",
    "PluginPackageLifecycleLedger",
    "PluginPackageLifecycleSnapshotV1",
    "PluginPackageRetentionSnapshotV1",
    "PluginPackageRetirementSetSourcePort",
    "plugin_package_gc_candidate_id",
]
