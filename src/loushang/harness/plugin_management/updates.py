from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal import FunctionalJournalRecordCodec
from loushang.harness.plugin_management.operations import (
    PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES,
    PluginManagementRecordCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)

PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION = 2
PLUGIN_MIGRATION_FENCE_VERSION = 1
PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION = 1
PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION = 2
PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION = 1
PLUGIN_UPDATE_OPERATION_RESULT_VERSION = 2
PLUGIN_UPDATE_OPERATION_EVENT_VERSION = 2

PluginMigrationFenceDisposition = Literal["not_applicable_unbound"]
PluginUpdateResultDisposition = Literal[
    "succeeded",
    "restart_required",
    "failed",
]
PluginUpdateOperationStatus = Literal["accepted", "running", "terminal"]
PluginUpdateProgressCode = Literal[
    "command_accepted",
    "update_staged",
    "migration_fence_satisfied",
    "desired_state_committing",
    "desired_state_committed",
    "update_restart_required",
    "desired_state_failed",
]
PluginUpdateChangedPackageField = Literal[
    "pluginVersion",
    "packageContentDigest",
    "dependencyLockDigest",
    "packageSourceIdentity",
]

PLUGIN_UPDATE_TERMINAL_ERROR_CODES = frozenset(
    set(PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES)
    | {
        "plugin_update_expected_package_mismatch",
        "plugin_update_not_installed",
        "plugin_update_target_not_new",
    }
)

_UPDATE_CHANGED_PACKAGE_FIELDS: tuple[PluginUpdateChangedPackageField, ...] = (
    "pluginVersion",
    "packageContentDigest",
    "dependencyLockDigest",
    "packageSourceIdentity",
)
_UPDATE_PROGRESS_CODES = frozenset(
    {
        "command_accepted",
        "update_staged",
        "migration_fence_satisfied",
        "desired_state_committing",
        "desired_state_committed",
        "update_restart_required",
        "desired_state_failed",
    }
)
_UPDATE_RESULT_DISPOSITIONS = frozenset(
    {"succeeded", "restart_required", "failed"}
)


@dataclass(frozen=True, slots=True)
class PluginManagementUpdateCommandV2:
    operation_id: str
    idempotency_key: str
    expected_inventory_revision: int
    installation_key: PluginInstallationKeyV1
    expected_package_revision: PluginPackageRevisionRefV1
    staged_package_revision: PluginPackageRevisionRefV1
    actor_id: str
    policy_revision: str
    approval_reference: str | None = None
    action: Literal["update"] = "update"
    command_version: int = PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation id"),
            (self.idempotency_key, "idempotency key"),
            (self.actor_id, "actor id"),
            (self.policy_revision, "policy revision"),
        ):
            _require_nonempty(value, name=name)
        _require_nonnegative_integer(
            self.expected_inventory_revision,
            name="expected inventory revision",
        )
        if self.approval_reference is not None:
            _require_nonempty(self.approval_reference, name="approval reference")
        if self.action != "update":
            raise ValueError("Plugin update command action must be update")
        _require_version(
            self.command_version,
            expected=PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION,
        )
        plugin_id = self.installation_key.plugin_id
        if (
            self.expected_package_revision.plugin_id != plugin_id
            or self.staged_package_revision.plugin_id != plugin_id
        ):
            raise ValueError(
                "Plugin update Package Revisions must match the Installation"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "actorId": self.actor_id,
            "approvalReference": self.approval_reference,
            "commandVersion": self.command_version,
            "expectedInventoryRevision": self.expected_inventory_revision,
            "expectedPackageRevision": self.expected_package_revision.to_dict(),
            "idempotencyKey": self.idempotency_key,
            "installationKey": self.installation_key.to_dict(),
            "operationId": self.operation_id,
            "policyRevision": self.policy_revision,
            "stagedPackageRevision": self.staged_package_revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginManagementUpdateCommandV2:
        document = _management_object(value, name="Plugin update command")
        _management_exact_fields(
            document,
            keys={
                "action",
                "actorId",
                "approvalReference",
                "commandVersion",
                "expectedInventoryRevision",
                "expectedPackageRevision",
                "idempotencyKey",
                "installationKey",
                "operationId",
                "policyRevision",
                "stagedPackageRevision",
            },
            name="Plugin update command",
        )
        _management_version(
            document.get("commandVersion"),
            expected=PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION,
        )
        try:
            action = _wire_string(document["action"], name="Plugin update action")
            if action != "update":
                raise ValueError("Plugin update command action must be update")
            return cls(
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                expected_inventory_revision=_wire_integer(
                    document["expectedInventoryRevision"],
                    name="expected inventory revision",
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                expected_package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["expectedPackageRevision"]
                ),
                staged_package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["stagedPackageRevision"]
                ),
                actor_id=_wire_string(document["actorId"], name="actor id"),
                policy_revision=_wire_string(
                    document["policyRevision"], name="policy revision"
                ),
                approval_reference=_wire_optional_string(
                    document["approvalReference"], name="approval reference"
                ),
                action="update",
                command_version=PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION,
            )
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_management_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginMigrationFenceV1:
    fence_id: str
    installation_key: PluginInstallationKeyV1
    expected_package_revision: PluginPackageRevisionRefV1
    staged_package_revision: PluginPackageRevisionRefV1
    disposition: PluginMigrationFenceDisposition = "not_applicable_unbound"
    schema_version: int = PLUGIN_MIGRATION_FENCE_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.fence_id, name="migration fence id")
        if self.disposition != "not_applicable_unbound":
            raise ValueError("Unsupported Plugin migration fence disposition")
        _require_version(self.schema_version, expected=PLUGIN_MIGRATION_FENCE_VERSION)
        plugin_id = self.installation_key.plugin_id
        if (
            self.expected_package_revision.plugin_id != plugin_id
            or self.staged_package_revision.plugin_id != plugin_id
        ):
            raise ValueError(
                "Plugin migration fence Package Revisions must match Installation"
            )

    def matches(self, command: PluginManagementUpdateCommandV2) -> bool:
        return (
            self.fence_id == command.operation_id
            and self.installation_key == command.installation_key
            and self.expected_package_revision == command.expected_package_revision
            and self.staged_package_revision == command.staged_package_revision
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "expectedPackageRevision": self.expected_package_revision.to_dict(),
            "fenceId": self.fence_id,
            "installationKey": self.installation_key.to_dict(),
            "schemaVersion": self.schema_version,
            "stagedPackageRevision": self.staged_package_revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginMigrationFenceV1:
        document = _management_object(value, name="Plugin migration fence")
        _management_exact_fields(
            document,
            keys={
                "disposition",
                "expectedPackageRevision",
                "fenceId",
                "installationKey",
                "schemaVersion",
                "stagedPackageRevision",
            },
            name="Plugin migration fence",
        )
        _management_version(
            document.get("schemaVersion"), expected=PLUGIN_MIGRATION_FENCE_VERSION
        )
        try:
            disposition = _wire_string(
                document["disposition"], name="Plugin migration fence disposition"
            )
            if disposition != "not_applicable_unbound":
                raise ValueError("Unsupported Plugin migration fence disposition")
            return cls(
                fence_id=_wire_string(
                    document["fenceId"], name="migration fence id"
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                expected_package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["expectedPackageRevision"]
                ),
                staged_package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["stagedPackageRevision"]
                ),
                disposition="not_applicable_unbound",
                schema_version=PLUGIN_MIGRATION_FENCE_VERSION,
            )
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_management_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginDesiredStateUpdateMutationV1:
    command: PluginManagementUpdateCommandV2
    desired_state: Literal["installed_disabled", "installed_enabled"]
    migration_fence: PluginMigrationFenceV1
    schema_version: int = PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION

    def __post_init__(self) -> None:
        if self.desired_state not in {"installed_disabled", "installed_enabled"}:
            raise ValueError("Plugin update mutation requires an installed state")
        if not self.migration_fence.matches(self.command):
            raise ValueError("Plugin update migration fence does not match command")
        _require_version(
            self.schema_version,
            expected=PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION,
        )

    @property
    def operation_id(self) -> str:
        return self.command.operation_id

    @property
    def idempotency_key(self) -> str:
        return self.command.idempotency_key

    @property
    def expected_inventory_revision(self) -> int:
        return self.command.expected_inventory_revision

    @property
    def installation_key(self) -> PluginInstallationKeyV1:
        return self.command.installation_key

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command.to_dict(),
            "desiredState": self.desired_state,
            "migrationFence": self.migration_fence.to_dict(),
            "schemaVersion": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDesiredStateUpdateMutationV1:
        document = _lifecycle_object(value, name="Plugin desired-state update mutation")
        _lifecycle_exact_fields(
            document,
            keys={"command", "desiredState", "migrationFence", "schemaVersion"},
            name="Plugin desired-state update mutation",
        )
        _lifecycle_version(
            document.get("schemaVersion"),
            expected=PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION,
        )
        try:
            desired_state = _wire_string(
                document["desiredState"], name="Plugin desired state"
            )
            if desired_state not in {"installed_disabled", "installed_enabled"}:
                raise ValueError("Plugin update mutation requires an installed state")
            return cls(
                command=PluginManagementUpdateCommandV2.from_dict(
                    document["command"]
                ),
                desired_state=cast(
                    Literal["installed_disabled", "installed_enabled"],
                    desired_state,
                ),
                migration_fence=PluginMigrationFenceV1.from_dict(
                    document["migrationFence"]
                ),
                schema_version=PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION,
            )
        except PluginLifecycleCodecError:
            raise
        except (PluginManagementRecordCodecError, TypeError, ValueError) as exc:
            raise _invalid_lifecycle_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginDesiredStateUpdateTransitionV2:
    inventory_revision: int
    mutation: PluginDesiredStateUpdateMutationV1
    previous_state: PluginInstallationStateV1
    committed_state: PluginInstallationStateV1
    transition_kind: Literal["update"] = "update"
    record_version: int = PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.inventory_revision, name="inventory revision")
        if self.transition_kind != "update":
            raise ValueError("Plugin update transition kind must be update")
        if self.inventory_revision != self.mutation.expected_inventory_revision + 1:
            raise ValueError(
                "Plugin update transition inventory revision does not match CAS"
            )
        key = self.mutation.installation_key
        if (
            self.previous_state.installation_key != key
            or self.committed_state.installation_key != key
        ):
            raise ValueError("Plugin update transition Installation keys do not match")
        if self.previous_state.selection.desired_state != self.mutation.desired_state:
            raise ValueError("Plugin update predecessor desired state does not match")
        if self.committed_state.selection.desired_state != self.mutation.desired_state:
            raise ValueError("Plugin update committed desired state does not match")
        if (
            self.previous_state.selection.package_revision
            != self.mutation.command.expected_package_revision
            or self.committed_state.selection.package_revision
            != self.mutation.command.staged_package_revision
        ):
            raise ValueError("Plugin update transition Package Revisions do not match")
        _require_version(
            self.record_version,
            expected=PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "committedState": self.committed_state.to_dict(),
            "inventoryRevision": self.inventory_revision,
            "mutation": self.mutation.to_dict(),
            "previousState": self.previous_state.to_dict(),
            "recordVersion": self.record_version,
            "transitionKind": self.transition_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDesiredStateUpdateTransitionV2:
        document = _lifecycle_object(value, name="Plugin desired-state update transition")
        _lifecycle_exact_fields(
            document,
            keys={
                "committedState",
                "inventoryRevision",
                "mutation",
                "previousState",
                "recordVersion",
                "transitionKind",
            },
            name="Plugin desired-state update transition",
        )
        _lifecycle_version(
            document.get("recordVersion"),
            expected=PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION,
        )
        try:
            kind = _wire_string(
                document["transitionKind"], name="Plugin update transition kind"
            )
            if kind != "update":
                raise ValueError("Plugin update transition kind must be update")
            return cls(
                inventory_revision=_wire_integer(
                    document["inventoryRevision"], name="inventory revision"
                ),
                mutation=PluginDesiredStateUpdateMutationV1.from_dict(
                    document["mutation"]
                ),
                previous_state=PluginInstallationStateV1.from_dict(
                    document["previousState"]
                ),
                committed_state=PluginInstallationStateV1.from_dict(
                    document["committedState"]
                ),
                transition_kind="update",
                record_version=PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION,
            )
        except PluginLifecycleCodecError:
            raise
        except (PluginManagementRecordCodecError, TypeError, ValueError) as exc:
            raise _invalid_lifecycle_record(str(exc)) from exc


PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginDesiredStateUpdateTransitionV2.to_dict,
    decoder=PluginDesiredStateUpdateTransitionV2.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginUpdateRestartRequirementV1:
    changed_package_fields: tuple[PluginUpdateChangedPackageField, ...]
    reason_code: Literal[
        "enabled_package_revision_changed"
    ] = "enabled_package_revision_changed"
    requirement_version: int = PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION

    def __post_init__(self) -> None:
        if self.reason_code != "enabled_package_revision_changed":
            raise ValueError("Unsupported Plugin update restart reason")
        if not self.changed_package_fields:
            raise ValueError("Plugin update restart reason requires changed fields")
        canonical = tuple(
            field
            for field in _UPDATE_CHANGED_PACKAGE_FIELDS
            if field in self.changed_package_fields
        )
        if self.changed_package_fields != canonical or len(canonical) != len(
            set(self.changed_package_fields)
        ):
            raise ValueError(
                "Plugin update changed Package fields must be unique and canonical"
            )
        _require_version(
            self.requirement_version,
            expected=PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "changedPackageFields": list(self.changed_package_fields),
            "reasonCode": self.reason_code,
            "requirementVersion": self.requirement_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginUpdateRestartRequirementV1:
        document = _management_object(
            value, name="Plugin update restart requirement"
        )
        _management_exact_fields(
            document,
            keys={"changedPackageFields", "reasonCode", "requirementVersion"},
            name="Plugin update restart requirement",
        )
        _management_version(
            document.get("requirementVersion"),
            expected=PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION,
        )
        try:
            reason = _wire_string(
                document["reasonCode"], name="Plugin update restart reason"
            )
            if reason != "enabled_package_revision_changed":
                raise ValueError("Unsupported Plugin update restart reason")
            fields_value = document["changedPackageFields"]
            if not isinstance(fields_value, list):
                raise ValueError("Changed Package fields must be a JSON array")
            fields = tuple(
                _wire_string(field, name="changed Package field")
                for field in fields_value
            )
            if any(field not in _UPDATE_CHANGED_PACKAGE_FIELDS for field in fields):
                raise ValueError("Unsupported changed Package field")
            return cls(
                changed_package_fields=cast(
                    tuple[PluginUpdateChangedPackageField, ...], fields
                ),
                reason_code="enabled_package_revision_changed",
                requirement_version=PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION,
            )
        except PluginManagementRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_management_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginUpdateOperationResultV2:
    disposition: PluginUpdateResultDisposition
    transition: PluginDesiredStateUpdateTransitionV2 | None
    restart_requirement: PluginUpdateRestartRequirementV1 | None
    error_code: str | None
    result_version: int = PLUGIN_UPDATE_OPERATION_RESULT_VERSION

    def __post_init__(self) -> None:
        if self.disposition not in _UPDATE_RESULT_DISPOSITIONS:
            raise ValueError("Unsupported Plugin update result disposition")
        _require_version(
            self.result_version, expected=PLUGIN_UPDATE_OPERATION_RESULT_VERSION
        )
        if self.disposition == "succeeded":
            if (
                self.transition is None
                or self.restart_requirement is not None
                or self.error_code is not None
            ):
                raise ValueError(
                    "Successful Plugin update requires only a transition"
                )
            return
        if self.disposition == "restart_required":
            if (
                self.transition is None
                or self.restart_requirement is None
                or self.error_code is not None
            ):
                raise ValueError(
                    "Restart-required Plugin update requires transition and reason"
                )
            return
        if (
            self.transition is not None
            or self.restart_requirement is not None
            or self.error_code is None
        ):
            raise ValueError("Failed Plugin update requires only an error code")
        if self.error_code not in PLUGIN_UPDATE_TERMINAL_ERROR_CODES:
            raise ValueError("Unsupported Plugin update terminal error code")

    @classmethod
    def succeeded(
        cls, *, transition: PluginDesiredStateUpdateTransitionV2
    ) -> PluginUpdateOperationResultV2:
        return cls(
            disposition="succeeded",
            transition=transition,
            restart_requirement=None,
            error_code=None,
        )

    @classmethod
    def restart_required(
        cls,
        *,
        transition: PluginDesiredStateUpdateTransitionV2,
        restart_requirement: PluginUpdateRestartRequirementV1,
    ) -> PluginUpdateOperationResultV2:
        return cls(
            disposition="restart_required",
            transition=transition,
            restart_requirement=restart_requirement,
            error_code=None,
        )

    @classmethod
    def failed(cls, *, error_code: str) -> PluginUpdateOperationResultV2:
        return cls(
            disposition="failed",
            transition=None,
            restart_requirement=None,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "errorCode": self.error_code,
            "restartRequirement": (
                None
                if self.restart_requirement is None
                else self.restart_requirement.to_dict()
            ),
            "resultVersion": self.result_version,
            "transition": (
                None if self.transition is None else self.transition.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginUpdateOperationResultV2:
        document = _management_object(value, name="Plugin update operation result")
        _management_exact_fields(
            document,
            keys={
                "disposition",
                "errorCode",
                "restartRequirement",
                "resultVersion",
                "transition",
            },
            name="Plugin update operation result",
        )
        _management_version(
            document.get("resultVersion"),
            expected=PLUGIN_UPDATE_OPERATION_RESULT_VERSION,
        )
        try:
            disposition = _wire_string(
                document["disposition"], name="Plugin update result disposition"
            )
            if disposition not in _UPDATE_RESULT_DISPOSITIONS:
                raise ValueError("Unsupported Plugin update result disposition")
            return cls(
                disposition=cast(PluginUpdateResultDisposition, disposition),
                transition=(
                    None
                    if document["transition"] is None
                    else PluginDesiredStateUpdateTransitionV2.from_dict(
                        document["transition"]
                    )
                ),
                restart_requirement=(
                    None
                    if document["restartRequirement"] is None
                    else PluginUpdateRestartRequirementV1.from_dict(
                        document["restartRequirement"]
                    )
                ),
                error_code=_wire_optional_string(
                    document["errorCode"], name="Plugin update error code"
                ),
                result_version=PLUGIN_UPDATE_OPERATION_RESULT_VERSION,
            )
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_management_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginUpdateOperationEventV2:
    journal_revision: int
    operation_revision: int
    command: PluginManagementUpdateCommandV2
    status: PluginUpdateOperationStatus
    progress_code: PluginUpdateProgressCode
    migration_fence: PluginMigrationFenceV1 | None
    result: PluginUpdateOperationResultV2 | None
    compensation_state: Literal["not_required"] = "not_required"
    record_version: int = PLUGIN_UPDATE_OPERATION_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        _require_positive_integer(self.operation_revision, name="operation revision")
        if self.status not in {"accepted", "running", "terminal"}:
            raise ValueError("Unsupported Plugin update operation status")
        if self.progress_code not in _UPDATE_PROGRESS_CODES:
            raise ValueError("Unsupported Plugin update progress code")
        if self.compensation_state != "not_required":
            raise ValueError("Unsupported PLC2-3 compensation state")
        _require_version(
            self.record_version, expected=PLUGIN_UPDATE_OPERATION_EVENT_VERSION
        )
        expected_status, expected_progress, requires_fence, requires_result = {
            1: ("accepted", "command_accepted", False, False),
            2: ("running", "update_staged", False, False),
            3: ("running", "migration_fence_satisfied", True, False),
            4: ("running", "desired_state_committing", True, False),
            5: ("terminal", None, True, True),
        }.get(self.operation_revision, (None, None, None, None))
        if expected_status is None or self.status != expected_status:
            raise ValueError("Plugin update operation revision does not match status")
        if expected_progress is not None and self.progress_code != expected_progress:
            raise ValueError("Plugin update operation revision does not match progress")
        if requires_fence != (self.migration_fence is not None):
            raise ValueError("Plugin update migration fence does not match progress")
        if requires_result != (self.result is not None):
            raise ValueError("Plugin update result does not match progress")
        if self.migration_fence is not None and not self.migration_fence.matches(
            self.command
        ):
            raise ValueError("Plugin update event migration fence does not match command")
        if self.result is None:
            return
        terminal_progress = {
            "succeeded": "desired_state_committed",
            "restart_required": "update_restart_required",
            "failed": "desired_state_failed",
        }[self.result.disposition]
        if self.progress_code != terminal_progress:
            raise ValueError("Plugin update terminal result does not match progress")
        if (
            self.result.transition is not None
            and self.result.transition.mutation.command != self.command
        ):
            raise ValueError("Plugin update result transition does not match command")

    @classmethod
    def accepted(
        cls, *, journal_revision: int, command: PluginManagementUpdateCommandV2
    ) -> PluginUpdateOperationEventV2:
        return cls(
            journal_revision=journal_revision,
            operation_revision=1,
            command=command,
            status="accepted",
            progress_code="command_accepted",
            migration_fence=None,
            result=None,
        )

    @classmethod
    def staged(
        cls, *, journal_revision: int, command: PluginManagementUpdateCommandV2
    ) -> PluginUpdateOperationEventV2:
        return cls(
            journal_revision=journal_revision,
            operation_revision=2,
            command=command,
            status="running",
            progress_code="update_staged",
            migration_fence=None,
            result=None,
        )

    @classmethod
    def migrating(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementUpdateCommandV2,
        migration_fence: PluginMigrationFenceV1,
    ) -> PluginUpdateOperationEventV2:
        return cls(
            journal_revision=journal_revision,
            operation_revision=3,
            command=command,
            status="running",
            progress_code="migration_fence_satisfied",
            migration_fence=migration_fence,
            result=None,
        )

    @classmethod
    def committing(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementUpdateCommandV2,
        migration_fence: PluginMigrationFenceV1,
    ) -> PluginUpdateOperationEventV2:
        return cls(
            journal_revision=journal_revision,
            operation_revision=4,
            command=command,
            status="running",
            progress_code="desired_state_committing",
            migration_fence=migration_fence,
            result=None,
        )

    @classmethod
    def terminal(
        cls,
        *,
        journal_revision: int,
        command: PluginManagementUpdateCommandV2,
        migration_fence: PluginMigrationFenceV1,
        result: PluginUpdateOperationResultV2,
    ) -> PluginUpdateOperationEventV2:
        return cls(
            journal_revision=journal_revision,
            operation_revision=5,
            command=command,
            status="terminal",
            progress_code=cast(
                PluginUpdateProgressCode,
                {
                    "succeeded": "desired_state_committed",
                    "restart_required": "update_restart_required",
                    "failed": "desired_state_failed",
                }[result.disposition],
            ),
            migration_fence=migration_fence,
            result=result,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command.to_dict(),
            "compensationState": self.compensation_state,
            "journalRevision": self.journal_revision,
            "migrationFence": (
                None if self.migration_fence is None else self.migration_fence.to_dict()
            ),
            "operationRevision": self.operation_revision,
            "progressCode": self.progress_code,
            "recordVersion": self.record_version,
            "result": None if self.result is None else self.result.to_dict(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginUpdateOperationEventV2:
        document = _management_object(value, name="Plugin update operation event")
        _management_exact_fields(
            document,
            keys={
                "command",
                "compensationState",
                "journalRevision",
                "migrationFence",
                "operationRevision",
                "progressCode",
                "recordVersion",
                "result",
                "status",
            },
            name="Plugin update operation event",
        )
        _management_version(
            document.get("recordVersion"),
            expected=PLUGIN_UPDATE_OPERATION_EVENT_VERSION,
        )
        try:
            status = _wire_string(
                document["status"], name="Plugin update operation status"
            )
            progress = _wire_string(
                document["progressCode"], name="Plugin update progress code"
            )
            compensation = _wire_string(
                document["compensationState"],
                name="Plugin update compensation state",
            )
            if status not in {"accepted", "running", "terminal"}:
                raise ValueError("Unsupported Plugin update operation status")
            if progress not in _UPDATE_PROGRESS_CODES:
                raise ValueError("Unsupported Plugin update progress code")
            if compensation != "not_required":
                raise ValueError("Unsupported PLC2-3 compensation state")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                operation_revision=_wire_integer(
                    document["operationRevision"], name="operation revision"
                ),
                command=PluginManagementUpdateCommandV2.from_dict(
                    document["command"]
                ),
                status=cast(PluginUpdateOperationStatus, status),
                progress_code=cast(PluginUpdateProgressCode, progress),
                migration_fence=(
                    None
                    if document["migrationFence"] is None
                    else PluginMigrationFenceV1.from_dict(
                        document["migrationFence"]
                    )
                ),
                result=(
                    None
                    if document["result"] is None
                    else PluginUpdateOperationResultV2.from_dict(document["result"])
                ),
                compensation_state="not_required",
                record_version=PLUGIN_UPDATE_OPERATION_EVENT_VERSION,
            )
        except PluginManagementRecordCodecError:
            raise
        except (PluginLifecycleCodecError, TypeError, ValueError) as exc:
            raise _invalid_management_record(str(exc)) from exc


PLUGIN_UPDATE_OPERATION_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginUpdateOperationEventV2.to_dict,
    decoder=PluginUpdateOperationEventV2.from_dict,
)


def changed_package_fields(
    previous: PluginPackageRevisionRefV1,
    staged: PluginPackageRevisionRefV1,
) -> tuple[PluginUpdateChangedPackageField, ...]:
    changed: list[PluginUpdateChangedPackageField] = []
    if previous.plugin_version != staged.plugin_version:
        changed.append("pluginVersion")
    if previous.package_content_digest != staged.package_content_digest:
        changed.append("packageContentDigest")
    if previous.dependency_lock_digest != staged.dependency_lock_digest:
        changed.append("dependencyLockDigest")
    if previous.package_source_identity != staged.package_source_identity:
        changed.append("packageSourceIdentity")
    return tuple(changed)


def migration_fence_for(
    command: PluginManagementUpdateCommandV2,
) -> PluginMigrationFenceV1:
    return PluginMigrationFenceV1(
        fence_id=command.operation_id,
        installation_key=command.installation_key,
        expected_package_revision=command.expected_package_revision,
        staged_package_revision=command.staged_package_revision,
    )


def _management_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_management_record(str(exc)) from exc


def _lifecycle_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_lifecycle_record(str(exc)) from exc


def _management_exact_fields(
    value: dict[str, object], *, keys: set[str], name: str
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _invalid_management_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )


def _lifecycle_exact_fields(
    value: dict[str, object], *, keys: set[str], name: str
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _invalid_lifecycle_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )


def _management_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginManagementRecordCodecError(
            "Unsupported Plugin management record version",
            code="unsupported_plugin_management_record_version",
        )


def _lifecycle_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginLifecycleCodecError(
            "Unsupported Plugin lifecycle record version",
            code="unsupported_plugin_lifecycle_record_version",
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


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_nonnegative_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin record version")


def _invalid_management_record(message: str) -> PluginManagementRecordCodecError:
    return PluginManagementRecordCodecError(
        message, code="invalid_plugin_management_record"
    )


def _invalid_lifecycle_record(message: str) -> PluginLifecycleCodecError:
    return PluginLifecycleCodecError(message, code="invalid_plugin_lifecycle_record")


__all__ = [
    "PLUGIN_DESIRED_STATE_UPDATE_MUTATION_VERSION",
    "PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_CODEC",
    "PLUGIN_DESIRED_STATE_UPDATE_TRANSITION_RECORD_VERSION",
    "PLUGIN_MANAGEMENT_UPDATE_COMMAND_VERSION",
    "PLUGIN_MIGRATION_FENCE_VERSION",
    "PLUGIN_UPDATE_OPERATION_EVENT_CODEC",
    "PLUGIN_UPDATE_OPERATION_EVENT_VERSION",
    "PLUGIN_UPDATE_OPERATION_RESULT_VERSION",
    "PLUGIN_UPDATE_RESTART_REQUIREMENT_VERSION",
    "PLUGIN_UPDATE_TERMINAL_ERROR_CODES",
    "PluginDesiredStateUpdateMutationV1",
    "PluginDesiredStateUpdateTransitionV2",
    "PluginManagementUpdateCommandV2",
    "PluginMigrationFenceV1",
    "PluginUpdateChangedPackageField",
    "PluginUpdateOperationEventV2",
    "PluginUpdateOperationResultV2",
    "PluginUpdateProgressCode",
    "PluginUpdateRestartRequirementV1",
    "PluginUpdateResultDisposition",
    "changed_package_fields",
    "migration_fence_for",
]
