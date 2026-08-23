from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, TypeVar, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRuntimeRecordCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import PluginDeclarationCodecError
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_PACKAGE_PIN_VERSION = 1
PLUGIN_PACKAGE_PIN_RELEASE_VERSION = 1
PLUGIN_CLEANUP_TASK_VERSION = 1
PLUGIN_CLEANUP_ATTEMPT_VERSION = 1
PLUGIN_CLEANUP_REPAIR_DECISION_VERSION = 1
PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION = 1
PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION = 1

PluginPackagePinKind = Literal[
    "cold_resume",
    "dependency_lock",
    "forensic_retention",
]
PluginCleanupCoordinationKind = Literal["graceful", "security"]
PluginCleanupDisposition = Literal[
    "succeeded",
    "retryable_failure",
    "terminal_failure",
]
PluginCleanupRepairAction = Literal["retry", "safe_abandon"]
PluginPackageLifecycleEventKind = Literal[
    "pin_acquired",
    "pin_released",
    "cleanup_prepared",
    "cleanup_attempted",
    "cleanup_repaired",
    "recovery_completed",
]

_PIN_KINDS = frozenset(
    {"cold_resume", "dependency_lock", "forensic_retention"}
)
_CLEANUP_DISPOSITIONS = frozenset(
    {"succeeded", "retryable_failure", "terminal_failure"}
)
_REPAIR_ACTIONS = frozenset({"retry", "safe_abandon"})
_RESULT_CODE_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-:"
)
_NestedT = TypeVar("_NestedT")


class PluginPackageLifecycleRecordCodecError(JournalCodecError):
    """Strict package-lifecycle journal record decoding failure."""


@dataclass(frozen=True, slots=True)
class PluginPackagePinV1:
    pin_id: str
    package_revision: PluginPackageRevisionRefV1
    pin_kind: PluginPackagePinKind
    operation_id: str
    idempotency_key: str
    holder_reference: str
    pin_version: int = PLUGIN_PACKAGE_PIN_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.pin_id, name="Plugin Package pin id")
        if self.pin_kind not in _PIN_KINDS:
            raise ValueError("Unsupported Plugin Package pin kind")
        for value, name in (
            (self.operation_id, "Plugin Package pin operation id"),
            (self.idempotency_key, "Plugin Package pin idempotency key"),
            (self.holder_reference, "Plugin Package pin holder reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(self.pin_version, expected=PLUGIN_PACKAGE_PIN_VERSION)
        if self.pin_id != plugin_package_pin_id(
            package_revision=self.package_revision,
            pin_kind=self.pin_kind,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            holder_reference=self.holder_reference,
        ):
            raise ValueError("Plugin Package pin id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        package_revision: PluginPackageRevisionRefV1,
        pin_kind: PluginPackagePinKind,
        operation_id: str,
        idempotency_key: str,
        holder_reference: str,
    ) -> PluginPackagePinV1:
        return cls(
            pin_id=plugin_package_pin_id(
                package_revision=package_revision,
                pin_kind=pin_kind,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                holder_reference=holder_reference,
            ),
            package_revision=package_revision,
            pin_kind=pin_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            holder_reference=holder_reference,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "holderReference": self.holder_reference,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "packageRevision": self.package_revision.to_dict(),
            "pinId": self.pin_id,
            "pinKind": self.pin_kind,
            "pinVersion": self.pin_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackagePinV1:
        document = _wire_object(value, name="Plugin Package pin")
        _wire_exact_fields(
            document,
            keys={
                "holderReference",
                "idempotencyKey",
                "operationId",
                "packageRevision",
                "pinId",
                "pinKind",
                "pinVersion",
            },
            name="Plugin Package pin",
        )
        _wire_version(document.get("pinVersion"), expected=PLUGIN_PACKAGE_PIN_VERSION)
        try:
            pin_kind = _wire_string(document["pinKind"], name="pin kind")
            if pin_kind not in _PIN_KINDS:
                raise ValueError("Unsupported Plugin Package pin kind")
            return cls(
                pin_id=_wire_string(document["pinId"], name="pin id"),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["packageRevision"]
                ),
                pin_kind=cast(PluginPackagePinKind, pin_kind),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                holder_reference=_wire_string(
                    document["holderReference"], name="holder reference"
                ),
                pin_version=PLUGIN_PACKAGE_PIN_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginPackagePinReleaseV1:
    pin_id: str
    operation_id: str
    idempotency_key: str
    release_reference: str
    release_version: int = PLUGIN_PACKAGE_PIN_RELEASE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.pin_id, name="Plugin Package pin id")
        for value, name in (
            (self.operation_id, "Plugin Package pin release operation id"),
            (self.idempotency_key, "Plugin Package pin release idempotency key"),
            (self.release_reference, "Plugin Package pin release reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(
            self.release_version,
            expected=PLUGIN_PACKAGE_PIN_RELEASE_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "pinId": self.pin_id,
            "releaseReference": self.release_reference,
            "releaseVersion": self.release_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackagePinReleaseV1:
        document = _wire_object(value, name="Plugin Package pin release")
        _wire_exact_fields(
            document,
            keys={
                "idempotencyKey",
                "operationId",
                "pinId",
                "releaseReference",
                "releaseVersion",
            },
            name="Plugin Package pin release",
        )
        _wire_version(
            document.get("releaseVersion"),
            expected=PLUGIN_PACKAGE_PIN_RELEASE_VERSION,
        )
        try:
            return cls(
                pin_id=_wire_string(document["pinId"], name="pin id"),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                release_reference=_wire_string(
                    document["releaseReference"], name="release reference"
                ),
                release_version=PLUGIN_PACKAGE_PIN_RELEASE_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginCleanupTaskV1:
    cleanup_id: str
    cleanup_lease_id: str
    source_runtime_revision: int
    source_family: PluginInstanceLeaseFamilyV1
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    coordination_kind: PluginCleanupCoordinationKind
    coordination_id: str
    retirement_target_id: str | None
    cleanup_kind: str
    operation_id: str
    idempotency_key: str
    cleanup_reference: str
    task_version: int = PLUGIN_CLEANUP_TASK_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.cleanup_id, name="Plugin cleanup id")
        _require_sha256(self.cleanup_lease_id, name="Plugin cleanup lease id")
        _require_positive_integer(
            self.source_runtime_revision,
            name="cleanup source runtime revision",
        )
        _require_sha256(self.coordination_id, name="cleanup coordination id")
        if self.coordination_kind not in {"graceful", "security"}:
            raise ValueError("Unsupported Plugin cleanup coordination kind")
        if self.source_family.lease_kind not in {
            "direct_host",
            "owner_generation",
        } or len(self.source_family.members) != 1:
            raise ValueError("Plugin cleanup requires one host/owner source family")
        member = self.source_family.members[0]
        if (
            member.installation_key != self.installation_key
            or member.instance_revision_ref != self.instance_revision_ref
            or member.package_revision != self.package_revision
        ):
            raise ValueError("Plugin cleanup source subject does not match")
        if self.coordination_kind == "security":
            if self.retirement_target_id is not None:
                raise ValueError("Security cleanup has no retirement target")
        elif self.source_family.lease_kind == "owner_generation":
            _require_sha256(
                self.retirement_target_id,
                name="cleanup retirement target id",
            )
        elif self.retirement_target_id is not None:
            raise ValueError("Direct-host cleanup has no retirement target")
        _require_result_code(self.cleanup_kind, name="Plugin cleanup kind")
        for value, name in (
            (self.operation_id, "Plugin cleanup operation id"),
            (self.idempotency_key, "Plugin cleanup idempotency key"),
            (self.cleanup_reference, "Plugin cleanup reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(self.task_version, expected=PLUGIN_CLEANUP_TASK_VERSION)
        expected_cleanup_id = plugin_cleanup_id(
            source_runtime_revision=self.source_runtime_revision,
            source_family=self.source_family,
            installation_key=self.installation_key,
            instance_revision_ref=self.instance_revision_ref,
            package_revision=self.package_revision,
            coordination_kind=self.coordination_kind,
            coordination_id=self.coordination_id,
            retirement_target_id=self.retirement_target_id,
            cleanup_kind=self.cleanup_kind,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            cleanup_reference=self.cleanup_reference,
        )
        if self.cleanup_id != expected_cleanup_id:
            raise ValueError("Plugin cleanup id does not match its fields")
        if self.cleanup_lease_id != plugin_cleanup_lease_id(
            cleanup_id=self.cleanup_id,
            package_revision=self.package_revision,
        ):
            raise ValueError("Plugin cleanup lease id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        source_runtime_revision: int,
        source_family: PluginInstanceLeaseFamilyV1,
        coordination_kind: PluginCleanupCoordinationKind,
        coordination_id: str,
        retirement_target_id: str | None,
        cleanup_kind: str,
        operation_id: str,
        idempotency_key: str,
        cleanup_reference: str,
    ) -> PluginCleanupTaskV1:
        member = source_family.members[0]
        cleanup_id = plugin_cleanup_id(
            source_runtime_revision=source_runtime_revision,
            source_family=source_family,
            installation_key=member.installation_key,
            instance_revision_ref=member.instance_revision_ref,
            package_revision=member.package_revision,
            coordination_kind=coordination_kind,
            coordination_id=coordination_id,
            retirement_target_id=retirement_target_id,
            cleanup_kind=cleanup_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            cleanup_reference=cleanup_reference,
        )
        return cls(
            cleanup_id=cleanup_id,
            cleanup_lease_id=plugin_cleanup_lease_id(
                cleanup_id=cleanup_id,
                package_revision=member.package_revision,
            ),
            source_runtime_revision=source_runtime_revision,
            source_family=source_family,
            installation_key=member.installation_key,
            instance_revision_ref=member.instance_revision_ref,
            package_revision=member.package_revision,
            coordination_kind=coordination_kind,
            coordination_id=coordination_id,
            retirement_target_id=retirement_target_id,
            cleanup_kind=cleanup_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            cleanup_reference=cleanup_reference,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cleanupId": self.cleanup_id,
            "cleanupKind": self.cleanup_kind,
            "cleanupLeaseId": self.cleanup_lease_id,
            "cleanupReference": self.cleanup_reference,
            "coordinationId": self.coordination_id,
            "coordinationKind": self.coordination_kind,
            "idempotencyKey": self.idempotency_key,
            "installationKey": self.installation_key.to_dict(),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "operationId": self.operation_id,
            "packageRevision": self.package_revision.to_dict(),
            "retirementTargetId": self.retirement_target_id,
            "sourceFamily": self.source_family.to_dict(),
            "sourceRuntimeRevision": self.source_runtime_revision,
            "taskVersion": self.task_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginCleanupTaskV1:
        document = _wire_object(value, name="Plugin cleanup task")
        _wire_exact_fields(
            document,
            keys={
                "cleanupId",
                "cleanupKind",
                "cleanupLeaseId",
                "cleanupReference",
                "coordinationId",
                "coordinationKind",
                "idempotencyKey",
                "installationKey",
                "instanceRevisionRef",
                "operationId",
                "packageRevision",
                "retirementTargetId",
                "sourceFamily",
                "sourceRuntimeRevision",
                "taskVersion",
            },
            name="Plugin cleanup task",
        )
        _wire_version(
            document.get("taskVersion"),
            expected=PLUGIN_CLEANUP_TASK_VERSION,
        )
        try:
            coordination_kind = _wire_string(
                document["coordinationKind"], name="coordination kind"
            )
            if coordination_kind not in {"graceful", "security"}:
                raise ValueError("Unsupported Plugin cleanup coordination kind")
            return cls(
                cleanup_id=_wire_string(document["cleanupId"], name="cleanup id"),
                cleanup_lease_id=_wire_string(
                    document["cleanupLeaseId"], name="cleanup lease id"
                ),
                source_runtime_revision=_wire_integer(
                    document["sourceRuntimeRevision"],
                    name="source runtime revision",
                ),
                source_family=PluginInstanceLeaseFamilyV1.from_dict(
                    document["sourceFamily"]
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["packageRevision"]
                ),
                coordination_kind=cast(
                    PluginCleanupCoordinationKind,
                    coordination_kind,
                ),
                coordination_id=_wire_string(
                    document["coordinationId"], name="coordination id"
                ),
                retirement_target_id=_wire_optional_string(
                    document["retirementTargetId"],
                    name="retirement target id",
                ),
                cleanup_kind=_wire_string(
                    document["cleanupKind"], name="cleanup kind"
                ),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                cleanup_reference=_wire_string(
                    document["cleanupReference"], name="cleanup reference"
                ),
                task_version=PLUGIN_CLEANUP_TASK_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginInstanceRuntimeRecordCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginCleanupAttemptV1:
    cleanup_id: str
    operation_id: str
    idempotency_key: str
    attempt: int
    disposition: PluginCleanupDisposition
    result_code: str
    retry_not_before_epoch_ms: int | None
    outcome_reference: str
    attempt_version: int = PLUGIN_CLEANUP_ATTEMPT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.cleanup_id, name="Plugin cleanup id")
        for value, name in (
            (self.operation_id, "Plugin cleanup attempt operation id"),
            (self.idempotency_key, "Plugin cleanup attempt idempotency key"),
            (self.outcome_reference, "Plugin cleanup outcome reference"),
        ):
            _require_nonempty(value, name=name)
        _require_positive_integer(self.attempt, name="Plugin cleanup attempt")
        if self.disposition not in _CLEANUP_DISPOSITIONS:
            raise ValueError("Unsupported Plugin cleanup disposition")
        _require_result_code(self.result_code, name="Plugin cleanup result code")
        if self.disposition == "retryable_failure":
            if self.retry_not_before_epoch_ms is not None:
                _require_nonnegative_integer(
                    self.retry_not_before_epoch_ms,
                    name="cleanup retry-not-before epoch milliseconds",
                )
        elif self.retry_not_before_epoch_ms is not None:
            raise ValueError("Terminal cleanup attempt has no retry timestamp")
        _require_version(
            self.attempt_version,
            expected=PLUGIN_CLEANUP_ATTEMPT_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "attemptVersion": self.attempt_version,
            "cleanupId": self.cleanup_id,
            "disposition": self.disposition,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "outcomeReference": self.outcome_reference,
            "resultCode": self.result_code,
            "retryNotBeforeEpochMs": self.retry_not_before_epoch_ms,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginCleanupAttemptV1:
        document = _wire_object(value, name="Plugin cleanup attempt")
        _wire_exact_fields(
            document,
            keys={
                "attempt",
                "attemptVersion",
                "cleanupId",
                "disposition",
                "idempotencyKey",
                "operationId",
                "outcomeReference",
                "resultCode",
                "retryNotBeforeEpochMs",
            },
            name="Plugin cleanup attempt",
        )
        _wire_version(
            document.get("attemptVersion"),
            expected=PLUGIN_CLEANUP_ATTEMPT_VERSION,
        )
        try:
            disposition = _wire_string(
                document["disposition"], name="cleanup disposition"
            )
            if disposition not in _CLEANUP_DISPOSITIONS:
                raise ValueError("Unsupported Plugin cleanup disposition")
            return cls(
                cleanup_id=_wire_string(document["cleanupId"], name="cleanup id"),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                attempt=_wire_integer(document["attempt"], name="attempt"),
                disposition=cast(PluginCleanupDisposition, disposition),
                result_code=_wire_string(
                    document["resultCode"], name="result code"
                ),
                retry_not_before_epoch_ms=_wire_optional_integer(
                    document["retryNotBeforeEpochMs"],
                    name="retry-not-before epoch milliseconds",
                ),
                outcome_reference=_wire_string(
                    document["outcomeReference"], name="outcome reference"
                ),
                attempt_version=PLUGIN_CLEANUP_ATTEMPT_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginCleanupRepairDecisionV1:
    decision_id: str
    cleanup_id: str
    repair_sequence: int
    action: PluginCleanupRepairAction
    operation_id: str
    idempotency_key: str
    authority_reference: str
    reason_code: str
    decision_version: int = PLUGIN_CLEANUP_REPAIR_DECISION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.decision_id, name="Plugin cleanup repair decision id")
        _require_sha256(self.cleanup_id, name="Plugin cleanup id")
        _require_positive_integer(
            self.repair_sequence,
            name="Plugin cleanup repair sequence",
        )
        if self.action not in _REPAIR_ACTIONS:
            raise ValueError("Unsupported Plugin cleanup repair action")
        for value, name in (
            (self.operation_id, "Plugin cleanup repair operation id"),
            (self.idempotency_key, "Plugin cleanup repair idempotency key"),
            (self.authority_reference, "Plugin cleanup repair authority"),
        ):
            _require_nonempty(value, name=name)
        _require_result_code(self.reason_code, name="Plugin cleanup repair reason")
        _require_version(
            self.decision_version,
            expected=PLUGIN_CLEANUP_REPAIR_DECISION_VERSION,
        )
        if self.decision_id != plugin_cleanup_repair_decision_id(
            cleanup_id=self.cleanup_id,
            repair_sequence=self.repair_sequence,
            action=self.action,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            authority_reference=self.authority_reference,
            reason_code=self.reason_code,
        ):
            raise ValueError("Plugin cleanup repair decision id does not match")

    @classmethod
    def create(
        cls,
        *,
        cleanup_id: str,
        repair_sequence: int,
        action: PluginCleanupRepairAction,
        operation_id: str,
        idempotency_key: str,
        authority_reference: str,
        reason_code: str,
    ) -> PluginCleanupRepairDecisionV1:
        return cls(
            decision_id=plugin_cleanup_repair_decision_id(
                cleanup_id=cleanup_id,
                repair_sequence=repair_sequence,
                action=action,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                authority_reference=authority_reference,
                reason_code=reason_code,
            ),
            cleanup_id=cleanup_id,
            repair_sequence=repair_sequence,
            action=action,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            authority_reference=authority_reference,
            reason_code=reason_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "authorityReference": self.authority_reference,
            "cleanupId": self.cleanup_id,
            "decisionId": self.decision_id,
            "decisionVersion": self.decision_version,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "reasonCode": self.reason_code,
            "repairSequence": self.repair_sequence,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginCleanupRepairDecisionV1:
        document = _wire_object(value, name="Plugin cleanup repair decision")
        _wire_exact_fields(
            document,
            keys={
                "action",
                "authorityReference",
                "cleanupId",
                "decisionId",
                "decisionVersion",
                "idempotencyKey",
                "operationId",
                "reasonCode",
                "repairSequence",
            },
            name="Plugin cleanup repair decision",
        )
        _wire_version(
            document.get("decisionVersion"),
            expected=PLUGIN_CLEANUP_REPAIR_DECISION_VERSION,
        )
        try:
            action = _wire_string(document["action"], name="repair action")
            if action not in _REPAIR_ACTIONS:
                raise ValueError("Unsupported Plugin cleanup repair action")
            return cls(
                decision_id=_wire_string(
                    document["decisionId"], name="decision id"
                ),
                cleanup_id=_wire_string(document["cleanupId"], name="cleanup id"),
                repair_sequence=_wire_integer(
                    document["repairSequence"], name="repair sequence"
                ),
                action=cast(PluginCleanupRepairAction, action),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                authority_reference=_wire_string(
                    document["authorityReference"], name="authority reference"
                ),
                reason_code=_wire_string(
                    document["reasonCode"], name="reason code"
                ),
                decision_version=PLUGIN_CLEANUP_REPAIR_DECISION_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginPackageRecoveryBarrierV1:
    barrier_id: str
    startup_id: str
    operation_id: str
    idempotency_key: str
    recovery_reference: str
    observed_desired_inventory_revision: int
    observed_instance_runtime_revision: int
    observed_package_journal_revision: int
    open_pin_ids: tuple[str, ...]
    open_cleanup_ids: tuple[str, ...]
    barrier_version: int = PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.barrier_id, name="Plugin Package recovery barrier id")
        for value, name in (
            (self.startup_id, "Plugin Package startup id"),
            (self.operation_id, "Plugin Package recovery operation id"),
            (self.idempotency_key, "Plugin Package recovery idempotency key"),
            (self.recovery_reference, "Plugin Package recovery reference"),
        ):
            _require_nonempty(value, name=name)
        for revision, revision_name in (
            (
                self.observed_desired_inventory_revision,
                "observed desired inventory revision",
            ),
            (
                self.observed_instance_runtime_revision,
                "observed Instance runtime revision",
            ),
            (
                self.observed_package_journal_revision,
                "observed Package journal revision",
            ),
        ):
            _require_nonnegative_integer(revision, name=revision_name)
        for values, name in (
            (self.open_pin_ids, "open Package pin ids"),
            (self.open_cleanup_ids, "open cleanup ids"),
        ):
            _require_sorted_unique_sha256(values, name=name)
        _require_version(
            self.barrier_version,
            expected=PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION,
        )
        if self.barrier_id != plugin_package_recovery_barrier_id(
            startup_id=self.startup_id,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            recovery_reference=self.recovery_reference,
            observed_desired_inventory_revision=(
                self.observed_desired_inventory_revision
            ),
            observed_instance_runtime_revision=(
                self.observed_instance_runtime_revision
            ),
            observed_package_journal_revision=(
                self.observed_package_journal_revision
            ),
            open_pin_ids=self.open_pin_ids,
            open_cleanup_ids=self.open_cleanup_ids,
        ):
            raise ValueError("Plugin Package recovery barrier id does not match")

    @classmethod
    def create(
        cls,
        *,
        startup_id: str,
        operation_id: str,
        idempotency_key: str,
        recovery_reference: str,
        observed_desired_inventory_revision: int,
        observed_instance_runtime_revision: int,
        observed_package_journal_revision: int,
        open_pin_ids: tuple[str, ...],
        open_cleanup_ids: tuple[str, ...],
    ) -> PluginPackageRecoveryBarrierV1:
        return cls(
            barrier_id=plugin_package_recovery_barrier_id(
                startup_id=startup_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                recovery_reference=recovery_reference,
                observed_desired_inventory_revision=(
                    observed_desired_inventory_revision
                ),
                observed_instance_runtime_revision=(
                    observed_instance_runtime_revision
                ),
                observed_package_journal_revision=(
                    observed_package_journal_revision
                ),
                open_pin_ids=open_pin_ids,
                open_cleanup_ids=open_cleanup_ids,
            ),
            startup_id=startup_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            recovery_reference=recovery_reference,
            observed_desired_inventory_revision=observed_desired_inventory_revision,
            observed_instance_runtime_revision=observed_instance_runtime_revision,
            observed_package_journal_revision=observed_package_journal_revision,
            open_pin_ids=open_pin_ids,
            open_cleanup_ids=open_cleanup_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "barrierId": self.barrier_id,
            "barrierVersion": self.barrier_version,
            "idempotencyKey": self.idempotency_key,
            "observedDesiredInventoryRevision": (
                self.observed_desired_inventory_revision
            ),
            "observedInstanceRuntimeRevision": (
                self.observed_instance_runtime_revision
            ),
            "observedPackageJournalRevision": (
                self.observed_package_journal_revision
            ),
            "openCleanupIds": list(self.open_cleanup_ids),
            "openPinIds": list(self.open_pin_ids),
            "operationId": self.operation_id,
            "recoveryReference": self.recovery_reference,
            "startupId": self.startup_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageRecoveryBarrierV1:
        document = _wire_object(value, name="Plugin Package recovery barrier")
        _wire_exact_fields(
            document,
            keys={
                "barrierId",
                "barrierVersion",
                "idempotencyKey",
                "observedDesiredInventoryRevision",
                "observedInstanceRuntimeRevision",
                "observedPackageJournalRevision",
                "openCleanupIds",
                "openPinIds",
                "operationId",
                "recoveryReference",
                "startupId",
            },
            name="Plugin Package recovery barrier",
        )
        _wire_version(
            document.get("barrierVersion"),
            expected=PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION,
        )
        try:
            return cls(
                barrier_id=_wire_string(document["barrierId"], name="barrier id"),
                startup_id=_wire_string(document["startupId"], name="startup id"),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                recovery_reference=_wire_string(
                    document["recoveryReference"], name="recovery reference"
                ),
                observed_desired_inventory_revision=_wire_integer(
                    document["observedDesiredInventoryRevision"],
                    name="observed desired inventory revision",
                ),
                observed_instance_runtime_revision=_wire_integer(
                    document["observedInstanceRuntimeRevision"],
                    name="observed Instance runtime revision",
                ),
                observed_package_journal_revision=_wire_integer(
                    document["observedPackageJournalRevision"],
                    name="observed Package journal revision",
                ),
                open_pin_ids=_wire_string_tuple(
                    document["openPinIds"], name="open pin ids"
                ),
                open_cleanup_ids=_wire_string_tuple(
                    document["openCleanupIds"], name="open cleanup ids"
                ),
                barrier_version=PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginPackageLifecycleEventV1:
    journal_revision: int
    event_kind: PluginPackageLifecycleEventKind
    pin: PluginPackagePinV1 | None
    pin_release: PluginPackagePinReleaseV1 | None
    cleanup_task: PluginCleanupTaskV1 | None
    cleanup_attempt: PluginCleanupAttemptV1 | None
    repair_decision: PluginCleanupRepairDecisionV1 | None
    recovery_barrier: PluginPackageRecoveryBarrierV1 | None
    record_version: int = PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        expected_by_kind = {
            "pin_acquired": (True, False, False, False, False, False),
            "pin_released": (False, True, False, False, False, False),
            "cleanup_prepared": (False, False, True, False, False, False),
            "cleanup_attempted": (False, False, False, True, False, False),
            "cleanup_repaired": (False, False, False, False, True, False),
            "recovery_completed": (False, False, False, False, False, True),
        }
        if self.event_kind not in expected_by_kind:
            raise ValueError("Unsupported Plugin Package lifecycle event kind")
        _require_version(
            self.record_version,
            expected=PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION,
        )
        actual = tuple(
            item is not None
            for item in (
                self.pin,
                self.pin_release,
                self.cleanup_task,
                self.cleanup_attempt,
                self.repair_decision,
                self.recovery_barrier,
            )
        )
        if actual != expected_by_kind[self.event_kind]:
            raise ValueError("Plugin Package lifecycle event payload is inconsistent")

    @classmethod
    def for_payload(
        cls,
        *,
        journal_revision: int,
        payload: (
            PluginPackagePinV1
            | PluginPackagePinReleaseV1
            | PluginCleanupTaskV1
            | PluginCleanupAttemptV1
            | PluginCleanupRepairDecisionV1
            | PluginPackageRecoveryBarrierV1
        ),
    ) -> PluginPackageLifecycleEventV1:
        if isinstance(payload, PluginPackagePinV1):
            return cls(
                journal_revision,
                "pin_acquired",
                payload,
                None,
                None,
                None,
                None,
                None,
            )
        if isinstance(payload, PluginPackagePinReleaseV1):
            return cls(
                journal_revision,
                "pin_released",
                None,
                payload,
                None,
                None,
                None,
                None,
            )
        if isinstance(payload, PluginCleanupTaskV1):
            return cls(
                journal_revision,
                "cleanup_prepared",
                None,
                None,
                payload,
                None,
                None,
                None,
            )
        if isinstance(payload, PluginCleanupAttemptV1):
            return cls(
                journal_revision,
                "cleanup_attempted",
                None,
                None,
                None,
                payload,
                None,
                None,
            )
        if isinstance(payload, PluginCleanupRepairDecisionV1):
            return cls(
                journal_revision,
                "cleanup_repaired",
                None,
                None,
                None,
                None,
                payload,
                None,
            )
        if not isinstance(payload, PluginPackageRecoveryBarrierV1):
            raise TypeError("Plugin Package lifecycle payload is required")
        return cls(
            journal_revision,
            "recovery_completed",
            None,
            None,
            None,
            None,
            None,
            payload,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cleanupAttempt": (
                None
                if self.cleanup_attempt is None
                else self.cleanup_attempt.to_dict()
            ),
            "cleanupTask": (
                None if self.cleanup_task is None else self.cleanup_task.to_dict()
            ),
            "eventKind": self.event_kind,
            "journalRevision": self.journal_revision,
            "pin": None if self.pin is None else self.pin.to_dict(),
            "pinRelease": (
                None if self.pin_release is None else self.pin_release.to_dict()
            ),
            "recordVersion": self.record_version,
            "recoveryBarrier": (
                None
                if self.recovery_barrier is None
                else self.recovery_barrier.to_dict()
            ),
            "repairDecision": (
                None
                if self.repair_decision is None
                else self.repair_decision.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageLifecycleEventV1:
        document = _wire_object(value, name="Plugin Package lifecycle event")
        _wire_exact_fields(
            document,
            keys={
                "cleanupAttempt",
                "cleanupTask",
                "eventKind",
                "journalRevision",
                "pin",
                "pinRelease",
                "recordVersion",
                "recoveryBarrier",
                "repairDecision",
            },
            name="Plugin Package lifecycle event",
        )
        _wire_version(
            document.get("recordVersion"),
            expected=PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION,
        )
        try:
            event_kind = _wire_string(document["eventKind"], name="event kind")
            if event_kind not in {
                "pin_acquired",
                "pin_released",
                "cleanup_prepared",
                "cleanup_attempted",
                "cleanup_repaired",
                "recovery_completed",
            }:
                raise ValueError("Unsupported Plugin Package lifecycle event kind")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                event_kind=cast(PluginPackageLifecycleEventKind, event_kind),
                pin=_wire_optional_nested(
                    document["pin"], PluginPackagePinV1.from_dict
                ),
                pin_release=_wire_optional_nested(
                    document["pinRelease"], PluginPackagePinReleaseV1.from_dict
                ),
                cleanup_task=_wire_optional_nested(
                    document["cleanupTask"], PluginCleanupTaskV1.from_dict
                ),
                cleanup_attempt=_wire_optional_nested(
                    document["cleanupAttempt"], PluginCleanupAttemptV1.from_dict
                ),
                repair_decision=_wire_optional_nested(
                    document["repairDecision"],
                    PluginCleanupRepairDecisionV1.from_dict,
                ),
                recovery_barrier=_wire_optional_nested(
                    document["recoveryBarrier"],
                    PluginPackageRecoveryBarrierV1.from_dict,
                ),
                record_version=PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION,
            )
        except PluginPackageLifecycleRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPackageLifecycleEventV1.to_dict,
    decoder=PluginPackageLifecycleEventV1.from_dict,
)


def plugin_package_pin_id(
    *,
    package_revision: PluginPackageRevisionRefV1,
    pin_kind: PluginPackagePinKind,
    operation_id: str,
    idempotency_key: str,
    holder_reference: str,
) -> str:
    return _derived_id(
        b"plugin-package-pin-v1\0",
        {
            "holderReference": holder_reference,
            "idempotencyKey": idempotency_key,
            "operationId": operation_id,
            "packageRevision": package_revision.to_dict(),
            "pinKind": pin_kind,
        },
    )


def plugin_cleanup_id(
    *,
    source_runtime_revision: int,
    source_family: PluginInstanceLeaseFamilyV1,
    installation_key: PluginInstallationKeyV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    package_revision: PluginPackageRevisionRefV1,
    coordination_kind: PluginCleanupCoordinationKind,
    coordination_id: str,
    retirement_target_id: str | None,
    cleanup_kind: str,
    operation_id: str,
    idempotency_key: str,
    cleanup_reference: str,
) -> str:
    return _derived_id(
        b"plugin-cleanup-task-v1\0",
        {
            "cleanupKind": cleanup_kind,
            "cleanupReference": cleanup_reference,
            "coordinationId": coordination_id,
            "coordinationKind": coordination_kind,
            "idempotencyKey": idempotency_key,
            "installationKey": installation_key.to_dict(),
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "operationId": operation_id,
            "packageRevision": package_revision.to_dict(),
            "retirementTargetId": retirement_target_id,
            "sourceFamily": source_family.to_dict(),
            "sourceRuntimeRevision": source_runtime_revision,
        },
    )


def plugin_cleanup_lease_id(
    *,
    cleanup_id: str,
    package_revision: PluginPackageRevisionRefV1,
) -> str:
    return _derived_id(
        b"plugin-cleanup-package-lease-v1\0",
        {
            "cleanupId": cleanup_id,
            "packageRevision": package_revision.to_dict(),
        },
    )


def plugin_cleanup_repair_decision_id(
    *,
    cleanup_id: str,
    repair_sequence: int,
    action: PluginCleanupRepairAction,
    operation_id: str,
    idempotency_key: str,
    authority_reference: str,
    reason_code: str,
) -> str:
    return _derived_id(
        b"plugin-cleanup-repair-decision-v1\0",
        {
            "action": action,
            "authorityReference": authority_reference,
            "cleanupId": cleanup_id,
            "idempotencyKey": idempotency_key,
            "operationId": operation_id,
            "reasonCode": reason_code,
            "repairSequence": repair_sequence,
        },
    )


def plugin_package_recovery_barrier_id(
    *,
    startup_id: str,
    operation_id: str,
    idempotency_key: str,
    recovery_reference: str,
    observed_desired_inventory_revision: int,
    observed_instance_runtime_revision: int,
    observed_package_journal_revision: int,
    open_pin_ids: tuple[str, ...],
    open_cleanup_ids: tuple[str, ...],
) -> str:
    return _derived_id(
        b"plugin-package-recovery-barrier-v1\0",
        {
            "idempotencyKey": idempotency_key,
            "observedDesiredInventoryRevision": observed_desired_inventory_revision,
            "observedInstanceRuntimeRevision": observed_instance_runtime_revision,
            "observedPackageJournalRevision": observed_package_journal_revision,
            "openCleanupIds": list(open_cleanup_ids),
            "openPinIds": list(open_pin_ids),
            "operationId": operation_id,
            "recoveryReference": recovery_reference,
            "startupId": startup_id,
        },
    )


def _derived_id(domain: bytes, value: dict[str, object]) -> str:
    return sha256(domain + StrictPluginJsonCodec.encode(value)).hexdigest()


def _wire_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_record(str(exc)) from exc


def _wire_exact_fields(
    value: dict[str, object], *, keys: set[str], name: str
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _invalid_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )


def _wire_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginPackageLifecycleRecordCodecError(
            "Unsupported Plugin Package lifecycle record version",
            code="unsupported_plugin_package_lifecycle_record_version",
        )


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _wire_optional_integer(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    return _wire_integer(value, name=name)


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return tuple(_wire_string(item, name=name) for item in value)


def _wire_optional_nested(
    value: object,
    decoder: Callable[[object], _NestedT],
) -> _NestedT | None:
    if value is None:
        return None
    return decoder(value)


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str | None, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_result_code(value: str, *, name: str) -> None:
    _require_nonempty(value, name=name)
    if len(value) > 128 or any(
        character not in _RESULT_CODE_CHARACTERS for character in value
    ):
        raise ValueError(f"{name} is not structural")


def _require_sorted_unique_sha256(values: tuple[str, ...], *, name: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{name} must be sorted and unique")
    for value in values:
        _require_sha256(value, name=name)


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin Package lifecycle record version")


def _invalid_record(message: str) -> PluginPackageLifecycleRecordCodecError:
    return PluginPackageLifecycleRecordCodecError(
        message,
        code="invalid_plugin_package_lifecycle_record",
    )


__all__ = [
    "PLUGIN_CLEANUP_ATTEMPT_VERSION",
    "PLUGIN_CLEANUP_REPAIR_DECISION_VERSION",
    "PLUGIN_CLEANUP_TASK_VERSION",
    "PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC",
    "PLUGIN_PACKAGE_LIFECYCLE_EVENT_VERSION",
    "PLUGIN_PACKAGE_PIN_RELEASE_VERSION",
    "PLUGIN_PACKAGE_PIN_VERSION",
    "PLUGIN_PACKAGE_RECOVERY_BARRIER_VERSION",
    "PluginCleanupAttemptV1",
    "PluginCleanupCoordinationKind",
    "PluginCleanupDisposition",
    "PluginCleanupRepairAction",
    "PluginCleanupRepairDecisionV1",
    "PluginCleanupTaskV1",
    "PluginPackageLifecycleEventKind",
    "PluginPackageLifecycleEventV1",
    "PluginPackageLifecycleRecordCodecError",
    "PluginPackagePinKind",
    "PluginPackagePinReleaseV1",
    "PluginPackagePinV1",
    "PluginPackageRecoveryBarrierV1",
    "plugin_cleanup_id",
    "plugin_cleanup_lease_id",
    "plugin_cleanup_repair_decision_id",
    "plugin_package_pin_id",
    "plugin_package_recovery_barrier_id",
]
