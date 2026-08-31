"""Durable one-way migration from legacy Plugin enablement inputs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationCommandV1,
    PluginManagementCommandPort,
    PluginManagementMigrationRecordV1,
    PluginManagementMigrationSnapshotV1,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec

PLUGIN_ENABLEMENT_MIGRATION_EPOCH = 1
PLUGIN_ENABLEMENT_MIGRATION_EVENT_VERSION = 1
PLUGIN_ENABLEMENT_MIGRATION_REQUEST_VERSION = 1
PLUGIN_ENABLEMENT_FINALIZATION_EVIDENCE_VERSION = 1
PLUGIN_ENABLEMENT_COMPATIBILITY_PROJECTION_VERSION = 1

PluginEnablementMigrationPhase = Literal[
    "accepted",
    "desired_committed",
    "compatibility_window",
    "finalized",
]
PluginEnablementMigrationDisposition = Literal["seeded", "already_authoritative"]

_PHASES = {
    "accepted",
    "desired_committed",
    "compatibility_window",
    "finalized",
}
_DISPOSITIONS = {"seeded", "already_authoritative"}
_ACTOR_ID = "harness:plugin-enablement-migration"
_POLICY_REVISION = "plugin-enablement-migration-v1"


class PluginEnablementMigrationError(RuntimeError):
    """Fail-closed migration, compatibility, or replay failure."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginEnablementMigrationRequestV1:
    installation_key: PluginInstallationKeyV1
    package_revision: PluginPackageRevisionRefV1 | None
    legacy_disabled: bool
    manifest_enabled_default: bool
    legacy_input_fingerprint: str
    migration_epoch: int = PLUGIN_ENABLEMENT_MIGRATION_EPOCH
    request_version: int = PLUGIN_ENABLEMENT_MIGRATION_REQUEST_VERSION

    def __post_init__(self) -> None:
        if (
            self.package_revision is not None
            and self.package_revision.plugin_id != self.installation_key.plugin_id
        ):
            raise ValueError("Migration Package Revision must match Installation")
        if type(self.legacy_disabled) is not bool:
            raise TypeError("Legacy disabled input must be boolean")
        if type(self.manifest_enabled_default) is not bool:
            raise TypeError("Manifest enabled default must be boolean")
        _require_sha256(
            self.legacy_input_fingerprint,
            name="legacy input fingerprint",
        )
        _require_positive(self.migration_epoch, name="migration epoch")
        if self.request_version != PLUGIN_ENABLEMENT_MIGRATION_REQUEST_VERSION:
            raise ValueError("Unsupported Plugin enablement migration request")

    @property
    def target_enabled(self) -> bool:
        return not self.legacy_disabled and self.manifest_enabled_default

    @property
    def migration_id(self) -> str:
        return hashlib.sha256(StrictPluginJsonCodec.encode(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "installationKey": self.installation_key.to_dict(),
            "legacyDisabled": self.legacy_disabled,
            "legacyInputFingerprint": self.legacy_input_fingerprint,
            "manifestEnabledDefault": self.manifest_enabled_default,
            "migrationEpoch": self.migration_epoch,
            "packageRevision": (
                None
                if self.package_revision is None
                else self.package_revision.to_dict()
            ),
            "requestVersion": self.request_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginEnablementMigrationRequestV1:
        document = _exact_dict(
            value,
            fields={
                "installationKey",
                "legacyDisabled",
                "legacyInputFingerprint",
                "manifestEnabledDefault",
                "migrationEpoch",
                "packageRevision",
                "requestVersion",
            },
            name="Plugin enablement migration request",
        )
        _wire_version(
            document["requestVersion"],
            expected=PLUGIN_ENABLEMENT_MIGRATION_REQUEST_VERSION,
        )
        try:
            return cls(
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                package_revision=(
                    None
                    if document["packageRevision"] is None
                    else PluginPackageRevisionRefV1.from_dict(
                        document["packageRevision"]
                    )
                ),
                legacy_disabled=_wire_bool(
                    document["legacyDisabled"], name="legacy disabled"
                ),
                manifest_enabled_default=_wire_bool(
                    document["manifestEnabledDefault"],
                    name="manifest enabled default",
                ),
                legacy_input_fingerprint=_wire_string(
                    document["legacyInputFingerprint"],
                    name="legacy input fingerprint",
                ),
                migration_epoch=_wire_positive(
                    document["migrationEpoch"], name="migration epoch"
                ),
            )
        except (JournalCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(
                "Plugin enablement migration request is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginEnablementFinalizationEvidenceV1:
    minimum_runtime_version: str
    minimum_migration_epoch: int
    backup_receipt: str
    restore_test_receipt: str
    roll_forward_procedure: str
    evidence_version: int = PLUGIN_ENABLEMENT_FINALIZATION_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.minimum_runtime_version, "minimum runtime version"),
            (self.backup_receipt, "backup receipt"),
            (self.restore_test_receipt, "restore test receipt"),
            (self.roll_forward_procedure, "roll-forward procedure"),
        ):
            _require_nonempty(value, name=name)
        _require_positive(
            self.minimum_migration_epoch,
            name="minimum migration epoch",
        )
        if self.evidence_version != PLUGIN_ENABLEMENT_FINALIZATION_EVIDENCE_VERSION:
            raise ValueError("Unsupported Plugin enablement finalization evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "backupReceipt": self.backup_receipt,
            "evidenceVersion": self.evidence_version,
            "minimumMigrationEpoch": self.minimum_migration_epoch,
            "minimumRuntimeVersion": self.minimum_runtime_version,
            "restoreTestReceipt": self.restore_test_receipt,
            "rollForwardProcedure": self.roll_forward_procedure,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginEnablementFinalizationEvidenceV1:
        document = _exact_dict(
            value,
            fields={
                "backupReceipt",
                "evidenceVersion",
                "minimumMigrationEpoch",
                "minimumRuntimeVersion",
                "restoreTestReceipt",
                "rollForwardProcedure",
            },
            name="Plugin enablement finalization evidence",
        )
        _wire_version(
            document["evidenceVersion"],
            expected=PLUGIN_ENABLEMENT_FINALIZATION_EVIDENCE_VERSION,
        )
        try:
            return cls(
                minimum_runtime_version=_wire_string(
                    document["minimumRuntimeVersion"],
                    name="minimum runtime version",
                ),
                minimum_migration_epoch=_wire_positive(
                    document["minimumMigrationEpoch"],
                    name="minimum migration epoch",
                ),
                backup_receipt=_wire_string(
                    document["backupReceipt"], name="backup receipt"
                ),
                restore_test_receipt=_wire_string(
                    document["restoreTestReceipt"], name="restore test receipt"
                ),
                roll_forward_procedure=_wire_string(
                    document["rollForwardProcedure"],
                    name="roll-forward procedure",
                ),
            )
        except (JournalCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(
                "Plugin enablement finalization evidence is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginEnablementMigrationEventV1:
    journal_revision: int
    phase: PluginEnablementMigrationPhase
    migration_id: str
    request: PluginEnablementMigrationRequestV1
    accepted_desired_inventory_revision: int
    prior_desired_history_revision: int | None
    disposition: PluginEnablementMigrationDisposition | None = None
    committed_desired_transition_revision: int | None = None
    operation_ids: tuple[str, ...] = ()
    finalization_evidence: PluginEnablementFinalizationEvidenceV1 | None = None
    event_version: int = PLUGIN_ENABLEMENT_MIGRATION_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.journal_revision, name="journal revision")
        if self.phase not in _PHASES:
            raise ValueError("Unsupported Plugin enablement migration phase")
        _require_sha256(self.migration_id, name="migration id")
        if self.migration_id != self.request.migration_id:
            raise ValueError("Plugin enablement migration id does not match request")
        _require_nonnegative(
            self.accepted_desired_inventory_revision,
            name="accepted desired inventory revision",
        )
        if self.prior_desired_history_revision is not None:
            _require_positive(
                self.prior_desired_history_revision,
                name="prior desired history revision",
            )
            if (
                self.prior_desired_history_revision
                > self.accepted_desired_inventory_revision
            ):
                raise ValueError("Prior desired history exceeds accepted inventory")
        if self.event_version != PLUGIN_ENABLEMENT_MIGRATION_EVENT_VERSION:
            raise ValueError("Unsupported Plugin enablement migration event")
        if self.operation_ids != tuple(sorted(set(self.operation_ids))):
            raise ValueError("Migration operation ids must be sorted and unique")
        for operation_id in self.operation_ids:
            _require_nonempty(operation_id, name="migration operation id")
        if self.phase == "accepted":
            if (
                any(
                    value is not None
                    for value in (
                        self.disposition,
                        self.committed_desired_transition_revision,
                        self.finalization_evidence,
                    )
                )
                or self.operation_ids
            ):
                raise ValueError("Accepted migration cannot carry outcome evidence")
            return
        if self.disposition not in _DISPOSITIONS:
            raise ValueError("Migration outcome disposition is required")
        if self.disposition == "seeded":
            if self.committed_desired_transition_revision is None:
                raise ValueError("Seeded migration requires a desired transition")
            _require_positive(
                self.committed_desired_transition_revision,
                name="committed desired transition revision",
            )
            if not self.operation_ids:
                raise ValueError("Seeded migration requires operation identities")
        elif self.committed_desired_transition_revision is not None:
            raise ValueError("Authoritative history cannot claim a seeded transition")
        if self.phase == "finalized":
            if self.finalization_evidence is None:
                raise ValueError("Finalized migration requires downgrade evidence")
            if (
                self.finalization_evidence.minimum_migration_epoch
                < self.request.migration_epoch
            ):
                raise ValueError("Finalization minimum epoch cannot permit downgrade")
        elif self.finalization_evidence is not None:
            raise ValueError("Only finalized migration can carry finalization evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptedDesiredInventoryRevision": (
                self.accepted_desired_inventory_revision
            ),
            "committedDesiredTransitionRevision": (
                self.committed_desired_transition_revision
            ),
            "disposition": self.disposition,
            "eventVersion": self.event_version,
            "finalizationEvidence": (
                None
                if self.finalization_evidence is None
                else self.finalization_evidence.to_dict()
            ),
            "journalRevision": self.journal_revision,
            "migrationId": self.migration_id,
            "operationIds": list(self.operation_ids),
            "phase": self.phase,
            "priorDesiredHistoryRevision": self.prior_desired_history_revision,
            "request": self.request.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginEnablementMigrationEventV1:
        document = _exact_dict(
            value,
            fields={
                "acceptedDesiredInventoryRevision",
                "committedDesiredTransitionRevision",
                "disposition",
                "eventVersion",
                "finalizationEvidence",
                "journalRevision",
                "migrationId",
                "operationIds",
                "phase",
                "priorDesiredHistoryRevision",
                "request",
            },
            name="Plugin enablement migration event",
        )
        _wire_version(
            document["eventVersion"],
            expected=PLUGIN_ENABLEMENT_MIGRATION_EVENT_VERSION,
        )
        try:
            phase = _wire_string(document["phase"], name="migration phase")
            if phase not in _PHASES:
                raise ValueError("Unsupported migration phase")
            disposition_value = document["disposition"]
            disposition = (
                None
                if disposition_value is None
                else _wire_string(disposition_value, name="migration disposition")
            )
            if disposition is not None and disposition not in _DISPOSITIONS:
                raise ValueError("Unsupported migration disposition")
            return cls(
                journal_revision=_wire_positive(
                    document["journalRevision"], name="journal revision"
                ),
                phase=cast(PluginEnablementMigrationPhase, phase),
                migration_id=_wire_string(document["migrationId"], name="migration id"),
                request=PluginEnablementMigrationRequestV1.from_dict(
                    document["request"]
                ),
                accepted_desired_inventory_revision=_wire_nonnegative(
                    document["acceptedDesiredInventoryRevision"],
                    name="accepted desired inventory revision",
                ),
                prior_desired_history_revision=_wire_optional_positive(
                    document["priorDesiredHistoryRevision"],
                    name="prior desired history revision",
                ),
                disposition=cast(
                    PluginEnablementMigrationDisposition | None,
                    disposition,
                ),
                committed_desired_transition_revision=_wire_optional_positive(
                    document["committedDesiredTransitionRevision"],
                    name="committed desired transition revision",
                ),
                operation_ids=_wire_string_tuple(
                    document["operationIds"], name="migration operation ids"
                ),
                finalization_evidence=(
                    None
                    if document["finalizationEvidence"] is None
                    else PluginEnablementFinalizationEvidenceV1.from_dict(
                        document["finalizationEvidence"]
                    )
                ),
            )
        except (JournalCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(
                "Plugin enablement migration event is invalid"
            ) from exc


PLUGIN_ENABLEMENT_MIGRATION_EVENT_CODEC = FunctionalJournalRecordCodec[
    PluginEnablementMigrationEventV1
](
    encoder=PluginEnablementMigrationEventV1.to_dict,
    decoder=PluginEnablementMigrationEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginEnablementMigrationSnapshotV1:
    journal_revision: int
    accepted_journal_revision: int
    phase: PluginEnablementMigrationPhase
    migration_id: str
    request: PluginEnablementMigrationRequestV1
    accepted_desired_inventory_revision: int
    prior_desired_history_revision: int | None
    disposition: PluginEnablementMigrationDisposition | None
    committed_desired_transition_revision: int | None
    operation_ids: tuple[str, ...]
    finalization_evidence: PluginEnablementFinalizationEvidenceV1 | None


class PluginEnablementMigrationJournal:
    """Append-only migration receipt owner, one immutable request per key."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def coordinate(self) -> AbstractContextManager[None]:
        """Serialize the complete accept/commit/window transaction."""

        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=".migration.lock",
        )

    def accept(
        self,
        request: PluginEnablementMigrationRequestV1,
        *,
        accepted_desired_inventory_revision: int,
        prior_desired_history_revision: int | None,
    ) -> PluginEnablementMigrationSnapshotV1:
        if not isinstance(request, PluginEnablementMigrationRequestV1):
            raise TypeError("Plugin enablement migration request is required")
        with self._exclusive():
            events = self._load_unlocked()
            snapshots = _project_events(events)
            existing = snapshots.get(request.installation_key)
            if existing is not None:
                if existing.request != request:
                    raise self._error(
                        "Legacy enablement input changed after migration acceptance",
                        code="plugin_enablement_migration_request_conflict",
                    )
                return existing
            event = PluginEnablementMigrationEventV1(
                journal_revision=len(events) + 1,
                phase="accepted",
                migration_id=request.migration_id,
                request=request,
                accepted_desired_inventory_revision=(
                    accepted_desired_inventory_revision
                ),
                prior_desired_history_revision=prior_desired_history_revision,
            )
            self._append_unlocked(event)
            return _snapshot_from_acceptance(event)

    def record_desired_commit(
        self,
        migration_id: str,
        *,
        disposition: PluginEnablementMigrationDisposition,
        committed_desired_transition_revision: int | None,
        operation_ids: tuple[str, ...],
    ) -> PluginEnablementMigrationSnapshotV1:
        with self._exclusive():
            events = self._load_unlocked()
            current = _snapshot_for_id(events, migration_id, path=self._path)
            if current.phase != "accepted":
                if (
                    current.disposition != disposition
                    or current.committed_desired_transition_revision
                    != committed_desired_transition_revision
                    or current.operation_ids != operation_ids
                ):
                    raise self._error(
                        "Plugin enablement migration desired outcome changed",
                        code="plugin_enablement_migration_outcome_conflict",
                    )
                return current
            event = _event_from_snapshot(
                current,
                journal_revision=len(events) + 1,
                phase="desired_committed",
                disposition=disposition,
                committed_desired_transition_revision=(
                    committed_desired_transition_revision
                ),
                operation_ids=operation_ids,
            )
            self._append_unlocked(event)
            return _snapshot_from_event(
                event, accepted=current.accepted_journal_revision
            )

    def enter_compatibility_window(
        self,
        migration_id: str,
    ) -> PluginEnablementMigrationSnapshotV1:
        with self._exclusive():
            events = self._load_unlocked()
            current = _snapshot_for_id(events, migration_id, path=self._path)
            if current.phase in {"compatibility_window", "finalized"}:
                return current
            if current.phase != "desired_committed":
                raise self._error(
                    "Migration desired state is not committed",
                    code="plugin_enablement_migration_phase_conflict",
                )
            event = _event_from_snapshot(
                current,
                journal_revision=len(events) + 1,
                phase="compatibility_window",
            )
            self._append_unlocked(event)
            return _snapshot_from_event(
                event, accepted=current.accepted_journal_revision
            )

    def finalize(
        self,
        migration_id: str,
        evidence: PluginEnablementFinalizationEvidenceV1,
    ) -> PluginEnablementMigrationSnapshotV1:
        if not isinstance(evidence, PluginEnablementFinalizationEvidenceV1):
            raise TypeError("Plugin enablement finalization evidence is required")
        with self._exclusive():
            events = self._load_unlocked()
            current = _snapshot_for_id(events, migration_id, path=self._path)
            if current.phase == "finalized":
                if current.finalization_evidence != evidence:
                    raise self._error(
                        "Plugin enablement finalization evidence changed",
                        code="plugin_enablement_migration_finalization_conflict",
                    )
                return current
            if current.phase != "compatibility_window":
                raise self._error(
                    "Plugin enablement compatibility window is not active",
                    code="plugin_enablement_migration_phase_conflict",
                )
            event = _event_from_snapshot(
                current,
                journal_revision=len(events) + 1,
                phase="finalized",
                finalization_evidence=evidence,
            )
            self._append_unlocked(event)
            return _snapshot_from_event(
                event, accepted=current.accepted_journal_revision
            )

    def snapshot(
        self,
        key: PluginInstallationKeyV1,
    ) -> PluginEnablementMigrationSnapshotV1 | None:
        with self._exclusive():
            return _project_events(self._load_unlocked()).get(key)

    def snapshots(self) -> tuple[PluginEnablementMigrationSnapshotV1, ...]:
        with self._exclusive():
            return tuple(
                sorted(
                    _project_events(self._load_unlocked()).values(),
                    key=lambda item: item.request.installation_key,
                )
            )

    def records(self) -> tuple[PluginEnablementMigrationEventV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def management_snapshot(self) -> PluginManagementMigrationSnapshotV1:
        """Project receipt phases for the common read model."""

        snapshots = self.snapshots()
        return PluginManagementMigrationSnapshotV1(
            journal_revision=max(
                (item.journal_revision for item in snapshots),
                default=0,
            ),
            records=tuple(
                PluginManagementMigrationRecordV1(
                    installation_key=item.request.installation_key,
                    phase=item.phase,
                    journal_revision=item.journal_revision,
                )
                for item in snapshots
            ),
        )

    def assert_runtime_compatible(self, *, supported_migration_epoch: int) -> None:
        _require_positive(supported_migration_epoch, name="supported migration epoch")
        for snapshot in self.snapshots():
            required = snapshot.request.migration_epoch
            if snapshot.finalization_evidence is not None:
                required = max(
                    required,
                    snapshot.finalization_evidence.minimum_migration_epoch,
                )
            if required > supported_migration_epoch:
                raise self._error(
                    "Runtime cannot honor the recorded Plugin migration epoch",
                    code="plugin_enablement_migration_epoch_unsupported",
                )

    def assert_legacy_mutation_allowed(self, key: PluginInstallationKeyV1) -> None:
        if self.snapshot(key) is not None:
            raise self._error(
                "Legacy Plugin enablement is read-only after migration acceptance",
                code="plugin_enablement_legacy_mutation_rejected",
            )

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _append_unlocked(self, event: PluginEnablementMigrationEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_ENABLEMENT_MIGRATION_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PluginEnablementMigrationEventV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PluginEnablementMigrationEventV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PLUGIN_ENABLEMENT_MIGRATION_EVENT_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
            events = snapshot.records
            if any(
                event.journal_revision != index
                for index, event in enumerate(events, start=1)
            ):
                raise ValueError("Migration journal revisions are not contiguous")
            _project_events(events)
            return events
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Plugin enablement migration journal is corrupt",
                code="plugin_enablement_migration_journal_corrupt",
            ) from exc

    def _error(self, message: str, *, code: str) -> PluginEnablementMigrationError:
        return PluginEnablementMigrationError(message, code=code, path=self._path)


class PluginDesiredStateMigrationPort(Protocol):
    def capture(
        self,
    ) -> tuple[
        PluginDesiredStateSnapshotV1,
        tuple[PluginDesiredStateJournalTransition, ...],
    ]: ...

    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]: ...


MigrationPhaseObserver = Callable[[PluginEnablementMigrationPhase], None]


class PluginEnablementMigrationCoordinator:
    """Replay-safe bridge from immutable legacy inputs to canonical commands."""

    def __init__(
        self,
        *,
        journal: PluginEnablementMigrationJournal,
        desired_state: PluginDesiredStateMigrationPort,
        commands: PluginManagementCommandPort,
        phase_observer: MigrationPhaseObserver | None = None,
    ) -> None:
        self._journal = journal
        self._desired_state = desired_state
        self._commands = commands
        self._phase_observer = phase_observer

    @property
    def journal(self) -> PluginEnablementMigrationJournal:
        return self._journal

    def migrate(
        self,
        request: PluginEnablementMigrationRequestV1,
    ) -> PluginEnablementMigrationSnapshotV1:
        if not isinstance(request, PluginEnablementMigrationRequestV1):
            raise TypeError("Plugin enablement migration request is required")
        with self._journal.coordinate():
            return self._migrate_serialized(request)

    def _migrate_serialized(
        self,
        request: PluginEnablementMigrationRequestV1,
    ) -> PluginEnablementMigrationSnapshotV1:
        self._journal.assert_runtime_compatible(
            supported_migration_epoch=PLUGIN_ENABLEMENT_MIGRATION_EPOCH
        )
        if request.migration_epoch != PLUGIN_ENABLEMENT_MIGRATION_EPOCH:
            raise PluginEnablementMigrationError(
                "Runtime cannot execute this Plugin migration epoch",
                code="plugin_enablement_migration_epoch_unsupported",
                path=self._journal.path,
            )
        existing = self._journal.snapshot(request.installation_key)
        if existing is None:
            snapshot, transitions = self._desired_state.capture()
            prior = _history_for(transitions, request.installation_key)
            current = self._journal.accept(
                request,
                accepted_desired_inventory_revision=snapshot.inventory_revision,
                prior_desired_history_revision=(
                    None if not prior else prior[-1].inventory_revision
                ),
            )
            self._observe("accepted")
        else:
            if existing.request != request:
                raise PluginEnablementMigrationError(
                    "Legacy enablement input changed after migration acceptance",
                    code="plugin_enablement_migration_request_conflict",
                    path=self._journal.path,
                )
            current = existing
        if current.phase == "accepted":
            disposition, revision, operation_ids = self._commit_desired(request)
            current = self._journal.record_desired_commit(
                request.migration_id,
                disposition=disposition,
                committed_desired_transition_revision=revision,
                operation_ids=operation_ids,
            )
            self._observe("desired_committed")
        if current.phase == "desired_committed":
            current = self._journal.enter_compatibility_window(request.migration_id)
            self._observe("compatibility_window")
        return current

    def finalize(
        self,
        migration_id: str,
        evidence: PluginEnablementFinalizationEvidenceV1,
    ) -> PluginEnablementMigrationSnapshotV1:
        with self._journal.coordinate():
            current = self._journal.finalize(migration_id, evidence)
        self._observe("finalized")
        return current

    def _commit_desired(
        self,
        request: PluginEnablementMigrationRequestV1,
    ) -> tuple[PluginEnablementMigrationDisposition, int | None, tuple[str, ...]]:
        for _attempt in range(64):
            snapshot, transitions = self._desired_state.capture()
            history = _history_for(transitions, request.installation_key)
            if not history:
                if request.package_revision is None:
                    raise PluginEnablementMigrationError(
                        "Never-seen Plugin migration requires an exact Package Revision",
                        code="plugin_enablement_migration_package_required",
                        path=self._journal.path,
                    )
                operation = self._submit(
                    request,
                    action="install",
                    desired_state="installed_disabled",
                    expected_inventory_revision=snapshot.inventory_revision,
                    package_revision=request.package_revision,
                )
                if _retryable_cas(operation):
                    continue
                _require_migration_success(operation, path=self._journal.path)
                continue
            owned = _owned_seed_history(history, request)
            if owned is None:
                return "already_authoritative", None, ()
            latest = history[-1]
            state = snapshot.installation(request.installation_key)
            if not request.target_enabled:
                if (
                    state.selection.desired_state == "installed_disabled"
                    and state.selection.package_revision == request.package_revision
                    and latest in owned
                ):
                    return (
                        "seeded",
                        latest.inventory_revision,
                        tuple(sorted(item.mutation.operation_id for item in owned)),
                    )
                return "already_authoritative", None, ()
            if (
                state.selection.desired_state == "installed_enabled"
                and state.selection.package_revision == request.package_revision
                and latest in owned
            ):
                return (
                    "seeded",
                    latest.inventory_revision,
                    tuple(sorted(item.mutation.operation_id for item in owned)),
                )
            if (
                state.selection.desired_state != "installed_disabled"
                or state.selection.package_revision != request.package_revision
                or latest not in owned
            ):
                return "already_authoritative", None, ()
            operation = self._submit(
                request,
                action="enable",
                desired_state="installed_enabled",
                expected_inventory_revision=snapshot.inventory_revision,
                package_revision=None,
            )
            if _retryable_cas(operation):
                continue
            _require_migration_success(operation, path=self._journal.path)
        raise PluginEnablementMigrationError(
            "Plugin enablement migration could not linearize",
            code="plugin_enablement_migration_busy",
            path=self._journal.path,
        )

    def _submit(
        self,
        request: PluginEnablementMigrationRequestV1,
        *,
        action: Literal["install", "enable"],
        desired_state: Literal["installed_disabled", "installed_enabled"],
        expected_inventory_revision: int,
        package_revision: PluginPackageRevisionRefV1 | None,
    ) -> PluginManagementOperationEventV1:
        operation_id = _migration_operation_id(
            request,
            action=action,
            expected_inventory_revision=expected_inventory_revision,
        )
        result = self._commands.submit(
            PluginManagementApplicationCommandV1(
                correlation_id=f"plugin-enablement-migration:{request.migration_id}",
                command=PluginManagementCommandV1(
                    action=action,
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=operation_id,
                        idempotency_key=operation_id,
                        expected_inventory_revision=expected_inventory_revision,
                        installation_key=request.installation_key,
                        desired_state=desired_state,
                        package_revision=package_revision,
                        actor_id=_ACTOR_ID,
                        policy_revision=_POLICY_REVISION,
                        approval_reference=_approval_reference(request),
                    ),
                ),
            )
        )
        if not isinstance(result.operation, PluginManagementOperationEventV1):
            raise PluginEnablementMigrationError(
                "Enablement migration received an incompatible operation record",
                code="plugin_enablement_migration_operation_incompatible",
                path=self._journal.path,
            )
        return result.operation

    def _observe(self, phase: PluginEnablementMigrationPhase) -> None:
        if self._phase_observer is not None:
            self._phase_observer(phase)


@dataclass(frozen=True, slots=True)
class PluginEnablementCompatibilityProjectionV1:
    desired_inventory_revision: int
    migration_journal_revision: int
    disabled_plugin_ids: tuple[str, ...]
    projection_version: int = PLUGIN_ENABLEMENT_COMPATIBILITY_PROJECTION_VERSION

    def __post_init__(self) -> None:
        _require_nonnegative(
            self.desired_inventory_revision,
            name="desired inventory revision",
        )
        _require_nonnegative(
            self.migration_journal_revision,
            name="migration journal revision",
        )
        if self.disabled_plugin_ids != tuple(sorted(set(self.disabled_plugin_ids))):
            raise ValueError("Disabled Plugin ids must be sorted and unique")
        if (
            self.projection_version
            != PLUGIN_ENABLEMENT_COMPATIBILITY_PROJECTION_VERSION
        ):
            raise ValueError("Unsupported enablement compatibility projection")

    def to_dict(self) -> dict[str, object]:
        return {
            "desiredInventoryRevision": self.desired_inventory_revision,
            "disabledPluginIds": list(self.disabled_plugin_ids),
            "migrationJournalRevision": self.migration_journal_revision,
            "projectionVersion": self.projection_version,
        }


class PluginEnablementCompatibilityProjector:
    """Derived downgrade view; never an independent selection owner."""

    def __init__(
        self,
        *,
        journal: PluginEnablementMigrationJournal,
        desired_state: PluginDesiredStateMigrationPort,
    ) -> None:
        self._journal = journal
        self._desired_state = desired_state

    def snapshot(
        self,
        *,
        product_id: str,
        installation_scope: Literal["process", "tenant", "workspace"],
        scope_id: str,
    ) -> PluginEnablementCompatibilityProjectionV1:
        desired = self._desired_state.snapshot()
        migrations = tuple(
            item
            for item in self._journal.snapshots()
            if item.request.installation_key.product_id == product_id
            and item.request.installation_key.installation_scope == installation_scope
            and item.request.installation_key.scope_id == scope_id
            and item.phase in {"compatibility_window", "finalized"}
        )
        disabled = tuple(
            sorted(
                item.request.installation_key.plugin_id
                for item in migrations
                if desired.installation(
                    item.request.installation_key
                ).selection.desired_state
                != "installed_enabled"
            )
        )
        return PluginEnablementCompatibilityProjectionV1(
            desired_inventory_revision=desired.inventory_revision,
            migration_journal_revision=max(
                (item.journal_revision for item in migrations),
                default=0,
            ),
            disabled_plugin_ids=disabled,
        )


def plugin_enablement_legacy_input_fingerprint(
    installation_key: PluginInstallationKeyV1,
    *,
    legacy_disabled: bool,
    manifest_enabled_default: bool,
) -> str:
    """Bind only immutable legacy selection inputs, never source availability."""

    if not isinstance(installation_key, PluginInstallationKeyV1):
        raise TypeError("Plugin Installation key is required")
    if type(legacy_disabled) is not bool:
        raise TypeError("Legacy disabled input must be boolean")
    if type(manifest_enabled_default) is not bool:
        raise TypeError("Manifest enabled default must be boolean")
    return hashlib.sha256(
        StrictPluginJsonCodec.encode(
            {
                "installationKey": installation_key.to_dict(),
                "legacyDisabled": legacy_disabled,
                "manifestEnabledDefault": manifest_enabled_default,
            }
        )
    ).hexdigest()


def _project_events(
    events: tuple[PluginEnablementMigrationEventV1, ...],
) -> dict[PluginInstallationKeyV1, PluginEnablementMigrationSnapshotV1]:
    snapshots: dict[PluginInstallationKeyV1, PluginEnablementMigrationSnapshotV1] = {}
    ids: set[str] = set()
    for event in events:
        key = event.request.installation_key
        current = snapshots.get(key)
        if event.phase == "accepted":
            if current is not None or event.migration_id in ids:
                raise ValueError("Migration acceptance is not unique")
            ids.add(event.migration_id)
            snapshots[key] = _snapshot_from_acceptance(event)
            continue
        if current is None:
            raise ValueError("Migration phase has no acceptance")
        expected_phase = {
            "accepted": "desired_committed",
            "desired_committed": "compatibility_window",
            "compatibility_window": "finalized",
            "finalized": None,
        }[current.phase]
        if (
            event.phase != expected_phase
            or event.migration_id != current.migration_id
            or event.request != current.request
            or event.accepted_desired_inventory_revision
            != current.accepted_desired_inventory_revision
            or event.prior_desired_history_revision
            != current.prior_desired_history_revision
        ):
            raise ValueError("Migration phase transition is inconsistent")
        if current.phase != "accepted" and (
            event.disposition != current.disposition
            or event.committed_desired_transition_revision
            != current.committed_desired_transition_revision
            or event.operation_ids != current.operation_ids
        ):
            raise ValueError("Migration desired outcome changed during replay")
        snapshots[key] = _snapshot_from_event(
            event,
            accepted=current.accepted_journal_revision,
        )
    return snapshots


def _snapshot_from_acceptance(
    event: PluginEnablementMigrationEventV1,
) -> PluginEnablementMigrationSnapshotV1:
    return _snapshot_from_event(event, accepted=event.journal_revision)


def _snapshot_from_event(
    event: PluginEnablementMigrationEventV1,
    *,
    accepted: int,
) -> PluginEnablementMigrationSnapshotV1:
    return PluginEnablementMigrationSnapshotV1(
        journal_revision=event.journal_revision,
        accepted_journal_revision=accepted,
        phase=event.phase,
        migration_id=event.migration_id,
        request=event.request,
        accepted_desired_inventory_revision=(event.accepted_desired_inventory_revision),
        prior_desired_history_revision=event.prior_desired_history_revision,
        disposition=event.disposition,
        committed_desired_transition_revision=(
            event.committed_desired_transition_revision
        ),
        operation_ids=event.operation_ids,
        finalization_evidence=event.finalization_evidence,
    )


def _event_from_snapshot(
    snapshot: PluginEnablementMigrationSnapshotV1,
    *,
    journal_revision: int,
    phase: PluginEnablementMigrationPhase,
    disposition: PluginEnablementMigrationDisposition | None = None,
    committed_desired_transition_revision: int | None = None,
    operation_ids: tuple[str, ...] | None = None,
    finalization_evidence: PluginEnablementFinalizationEvidenceV1 | None = None,
) -> PluginEnablementMigrationEventV1:
    return PluginEnablementMigrationEventV1(
        journal_revision=journal_revision,
        phase=phase,
        migration_id=snapshot.migration_id,
        request=snapshot.request,
        accepted_desired_inventory_revision=(
            snapshot.accepted_desired_inventory_revision
        ),
        prior_desired_history_revision=snapshot.prior_desired_history_revision,
        disposition=snapshot.disposition if disposition is None else disposition,
        committed_desired_transition_revision=(
            snapshot.committed_desired_transition_revision
            if committed_desired_transition_revision is None
            else committed_desired_transition_revision
        ),
        operation_ids=(
            snapshot.operation_ids if operation_ids is None else operation_ids
        ),
        finalization_evidence=finalization_evidence,
    )


def _snapshot_for_id(
    events: tuple[PluginEnablementMigrationEventV1, ...],
    migration_id: str,
    *,
    path: Path,
) -> PluginEnablementMigrationSnapshotV1:
    _require_sha256(migration_id, name="migration id")
    for snapshot in _project_events(events).values():
        if snapshot.migration_id == migration_id:
            return snapshot
    raise PluginEnablementMigrationError(
        "Plugin enablement migration was not accepted",
        code="plugin_enablement_migration_not_found",
        path=path,
    )


def _history_for(
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
    key: PluginInstallationKeyV1,
) -> tuple[PluginDesiredStateJournalTransition, ...]:
    return tuple(item for item in transitions if item.mutation.installation_key == key)


def _owned_seed_history(
    history: tuple[PluginDesiredStateJournalTransition, ...],
    request: PluginEnablementMigrationRequestV1,
) -> tuple[PluginDesiredStateTransitionV1, ...] | None:
    owned: list[PluginDesiredStateTransitionV1] = []
    approval = _approval_reference(request)
    for index, transition in enumerate(history):
        if not isinstance(transition, PluginDesiredStateTransitionV1):
            return None
        mutation = transition.mutation
        action: Literal["install", "enable"] = (
            "install" if index == 0 else "enable"
        )
        expected_state = (
            "installed_disabled" if action == "install" else "installed_enabled"
        )
        expected_package = request.package_revision if action == "install" else None
        if (
            index > 1
            or (index == 1 and not request.target_enabled)
            or transition.transition_kind != action
            or mutation.desired_state != expected_state
            or mutation.package_revision != expected_package
            or mutation.actor_id != _ACTOR_ID
            or mutation.policy_revision != _POLICY_REVISION
            or mutation.approval_reference != approval
            or mutation.operation_id
            != _migration_operation_id(
                request,
                action=action,
                expected_inventory_revision=mutation.expected_inventory_revision,
            )
            or mutation.idempotency_key != mutation.operation_id
        ):
            return None
        owned.append(transition)
    return tuple(owned)


def _migration_operation_id(
    request: PluginEnablementMigrationRequestV1,
    *,
    action: Literal["install", "enable"],
    expected_inventory_revision: int,
) -> str:
    identity = hashlib.sha256(
        StrictPluginJsonCodec.encode(
            {
                "action": action,
                "expectedInventoryRevision": expected_inventory_revision,
                "migrationId": request.migration_id,
            }
        )
    ).hexdigest()
    return f"plugin-enablement-migration:{identity}"


def _approval_reference(request: PluginEnablementMigrationRequestV1) -> str:
    return f"plugin-enablement-migration:{request.migration_id}"


def _retryable_cas(operation: PluginManagementOperationEventV1) -> bool:
    return (
        operation.result is not None
        and operation.result.disposition == "failed"
        and operation.result.error_code == "plugin_inventory_revision_conflict"
    )


def _require_migration_success(
    operation: PluginManagementOperationEventV1,
    *,
    path: Path,
) -> None:
    result = operation.result
    if result is not None and result.disposition == "succeeded":
        return
    raise PluginEnablementMigrationError(
        "Plugin enablement desired-state command failed",
        code=(
            "plugin_enablement_migration_management_failed"
            if result is None or result.error_code is None
            else result.error_code
        ),
        path=path,
    )


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _invalid_record(f"{name} fields are invalid")
    return cast(dict[str, object], value)


def _wire_string(value: object, *, name: str) -> str:
    _require_nonempty(value, name=name)
    return cast(str, value)


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise _invalid_record(f"{name} must be boolean")
    return cast(bool, value)


def _wire_positive(value: object, *, name: str) -> int:
    _require_positive(value, name=name)
    return cast(int, value)


def _wire_nonnegative(value: object, *, name: str) -> int:
    _require_nonnegative(value, name=name)
    return cast(int, value)


def _wire_optional_positive(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    return _wire_positive(value, name=name)


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise _invalid_record(f"{name} must be a list")
    return tuple(_wire_string(item, name=name) for item in cast(list[object], value))


def _wire_version(value: object, *, expected: int) -> None:
    if type(value) is not int or value != expected:
        raise _invalid_record("Unsupported Plugin enablement migration record version")


def _require_nonempty(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty")


def _require_positive(value: object, *, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be positive")


def _require_nonnegative(value: object, *, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _invalid_record(message: str) -> JournalCodecError:
    return JournalCodecError(
        message,
        code="invalid_plugin_enablement_migration_record",
    )


__all__ = [
    "PLUGIN_ENABLEMENT_COMPATIBILITY_PROJECTION_VERSION",
    "PLUGIN_ENABLEMENT_FINALIZATION_EVIDENCE_VERSION",
    "PLUGIN_ENABLEMENT_MIGRATION_EPOCH",
    "PLUGIN_ENABLEMENT_MIGRATION_EVENT_CODEC",
    "PLUGIN_ENABLEMENT_MIGRATION_EVENT_VERSION",
    "PLUGIN_ENABLEMENT_MIGRATION_REQUEST_VERSION",
    "PluginEnablementCompatibilityProjectionV1",
    "PluginEnablementCompatibilityProjector",
    "PluginEnablementFinalizationEvidenceV1",
    "PluginEnablementMigrationCoordinator",
    "PluginEnablementMigrationDisposition",
    "PluginEnablementMigrationError",
    "PluginEnablementMigrationEventV1",
    "PluginEnablementMigrationJournal",
    "PluginEnablementMigrationPhase",
    "PluginEnablementMigrationRequestV1",
    "PluginEnablementMigrationSnapshotV1",
    "plugin_enablement_legacy_input_fingerprint",
]
