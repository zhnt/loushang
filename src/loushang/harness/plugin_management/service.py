from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

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
from loushang.harness.plugin_management.journal_codecs import (
    PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC,
    PluginDesiredStateJournalTransition,
    PluginManagementOperationEvent,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.operations import (
    PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementOperationResultV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementError,
    PluginRetirementIntentLedger,
    PluginRetirementIntentSnapshotV1,
    PluginRetirementIntentV1,
    retirement_intent_for_transition,
)
from loushang.harness.plugin_management.updates import (
    PLUGIN_UPDATE_TERMINAL_ERROR_CODES,
    PluginDesiredStateUpdateMutationV1,
    PluginDesiredStateUpdateTransitionV2,
    PluginManagementUpdateCommandV2,
    PluginMigrationFenceV1,
    PluginUpdateOperationEventV2,
    PluginUpdateOperationResultV2,
    PluginUpdateRestartRequirementV1,
    changed_package_fields,
    migration_fence_for,
)

_TERMINAL_LEDGER_FAILURE_CODES = frozenset(
    PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES - {"plugin_installation_already_enabled"}
)
_UPDATE_TERMINAL_LEDGER_FAILURE_CODES = frozenset(
    PLUGIN_UPDATE_TERMINAL_ERROR_CODES - {"plugin_installation_already_enabled"}
)

PluginManagementCommand = PluginManagementCommandV1 | PluginManagementUpdateCommandV2


class PluginDesiredStateLedgerPort(Protocol):
    @property
    def path(self) -> Path: ...

    def commit(
        self,
        mutation: PluginDesiredStateMutationV1,
    ) -> PluginDesiredStateTransitionV1: ...

    def commit_update(
        self,
        mutation: PluginDesiredStateUpdateMutationV1,
    ) -> PluginDesiredStateUpdateTransitionV2: ...

    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]: ...


class PluginRetirementIntentLedgerPort(Protocol):
    @property
    def path(self) -> Path: ...

    def request_for(
        self,
        transition: PluginDesiredStateJournalTransition,
    ) -> PluginRetirementIntentV1 | None: ...

    def snapshot(self) -> PluginRetirementIntentSnapshotV1: ...


class PluginManagementError(RuntimeError):
    """Fail-closed management-command error with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(slots=True)
class _ReplayedOperations:
    events: tuple[PluginManagementOperationEvent, ...]
    latest_by_operation: dict[str, PluginManagementOperationEvent]
    operation_by_idempotency: dict[str, str]
    accepted_journal_revision: dict[str, int]


class PluginManagementService:
    """Sole PLC2-2/PLC2-3 command authority over inert Plugin desired state."""

    def __init__(
        self,
        *,
        desired_state: PluginDesiredStateLedgerPort,
        operation_journal_path: str | Path,
        retirement_intents: PluginRetirementIntentLedgerPort | None = None,
    ) -> None:
        self._desired_state = desired_state
        self._path = Path(operation_journal_path)
        self._retirement_intents = retirement_intents or PluginRetirementIntentLedger(
            self._path.with_name(f"{self._path.name}.retirement-intents")
        )
        journal_paths = {
            self._path.resolve(),
            desired_state.path.resolve(),
            self._retirement_intents.path.resolve(),
        }
        if len(journal_paths) != 3:
            raise ValueError(
                "Plugin operation, desired-state and retirement journals must be distinct"
            )
        self._unlocked_durability = replace(
            DURABLE_LOCKED_JOURNAL,
            locking=False,
        )
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def operation_journal_path(self) -> Path:
        return self._path

    @property
    def retirement_intent_journal_path(self) -> Path:
        return self._retirement_intents.path

    def submit(
        self,
        command: PluginManagementCommand,
    ) -> PluginManagementOperationEvent:
        if not isinstance(
            command, (PluginManagementCommandV1, PluginManagementUpdateCommandV2)
        ):
            raise TypeError("Plugin management command is required")
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            existing = self._existing_operation(replayed, command)
            if existing is not None:
                if existing.status == "terminal":
                    return existing
                return self._execute_unlocked(
                    command,
                    latest=existing,
                    journal_revision=len(replayed.events),
                )

            self._reject_busy_installation(replayed, _installation_key(command))
            if isinstance(command, PluginManagementCommandV1):
                accepted: PluginManagementOperationEvent = (
                    PluginManagementOperationEventV1.accepted(
                        journal_revision=len(replayed.events) + 1,
                        command=command,
                    )
                )
            else:
                accepted = PluginUpdateOperationEventV2.accepted(
                    journal_revision=len(replayed.events) + 1,
                    command=command,
                )
            self._append_unlocked(accepted)
            return self._execute_unlocked(
                command,
                latest=accepted,
                journal_revision=accepted.journal_revision,
            )

    def recover(self) -> tuple[PluginManagementOperationEvent, ...]:
        """Recover accepted/running operations in original acceptance order."""

        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            pending = tuple(
                sorted(
                    (
                        event
                        for event in replayed.latest_by_operation.values()
                        if event.status != "terminal"
                    ),
                    key=lambda event: replayed.accepted_journal_revision[
                        event.command.operation_id
                    ],
                )
            )
            recovered: list[PluginManagementOperationEvent] = []
            journal_revision = len(replayed.events)
            for event in pending:
                terminal = self._execute_unlocked(
                    event.command,
                    latest=event,
                    journal_revision=journal_revision,
                )
                recovered.append(terminal)
                journal_revision = terminal.journal_revision
            return tuple(recovered)

    def operations(self) -> tuple[PluginManagementOperationEvent, ...]:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        return tuple(
            sorted(
                replayed.latest_by_operation.values(),
                key=lambda event: replayed.accepted_journal_revision[
                    event.command.operation_id
                ],
            )
        )

    def operation(
        self,
        operation_id: str,
    ) -> PluginManagementOperationEvent | None:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Plugin management operation id must be non-empty")
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        return replayed.latest_by_operation.get(operation_id)

    def _execute_unlocked(
        self,
        command: PluginManagementCommand,
        *,
        latest: PluginManagementOperationEvent,
        journal_revision: int,
    ) -> PluginManagementOperationEvent:
        if isinstance(command, PluginManagementUpdateCommandV2):
            if not isinstance(latest, PluginUpdateOperationEventV2):
                raise _corrupt(
                    self._path,
                    "Plugin update operation changed record family",
                )
            return self._execute_update_unlocked(
                command,
                latest=latest,
                journal_revision=journal_revision,
            )
        if not isinstance(latest, PluginManagementOperationEventV1):
            raise _corrupt(
                self._path,
                "Plugin management operation changed record family",
            )
        if latest.status == "accepted":
            running = PluginManagementOperationEventV1.running(
                journal_revision=journal_revision + 1,
                command=command,
            )
            self._append_unlocked(running)
            journal_revision = running.journal_revision
        elif latest.status != "running":
            raise _corrupt(
                self._path,
                "Plugin management operation cannot be resumed from terminal",
            )

        command_error = self._command_state_error(command)
        if command_error is not None:
            result = PluginManagementOperationResultV1.failed(
                error_code=command_error,
            )
        else:
            try:
                transition = self._desired_state.commit(command.mutation)
            except PluginLifecycleError as exc:
                if exc.code not in _TERMINAL_LEDGER_FAILURE_CODES:
                    raise
                result = PluginManagementOperationResultV1.failed(
                    error_code=exc.code,
                )
            else:
                self._handoff_retirement(transition)
                result = PluginManagementOperationResultV1.succeeded(
                    transition=transition,
                )

        terminal = PluginManagementOperationEventV1.terminal(
            journal_revision=journal_revision + 1,
            command=command,
            result=result,
        )
        self._append_unlocked(terminal)
        return terminal

    def _execute_update_unlocked(
        self,
        command: PluginManagementUpdateCommandV2,
        *,
        latest: PluginUpdateOperationEventV2,
        journal_revision: int,
    ) -> PluginUpdateOperationEventV2:
        fence = migration_fence_for(command)
        if latest.operation_revision == 1:
            latest = PluginUpdateOperationEventV2.staged(
                journal_revision=journal_revision + 1,
                command=command,
            )
            self._append_unlocked(latest)
            journal_revision = latest.journal_revision
        if latest.operation_revision == 2:
            latest = PluginUpdateOperationEventV2.migrating(
                journal_revision=journal_revision + 1,
                command=command,
                migration_fence=fence,
            )
            self._append_unlocked(latest)
            journal_revision = latest.journal_revision
        if latest.operation_revision == 3:
            latest = PluginUpdateOperationEventV2.committing(
                journal_revision=journal_revision + 1,
                command=command,
                migration_fence=fence,
            )
            self._append_unlocked(latest)
            journal_revision = latest.journal_revision
        if latest.operation_revision != 4:
            raise _corrupt(
                self._path,
                "Plugin update operation cannot be resumed from its current stage",
            )

        mutation, preparation_error = self._prepare_update_mutation(command, fence)
        if preparation_error is not None:
            result = PluginUpdateOperationResultV2.failed(
                error_code=preparation_error
            )
        else:
            if mutation is None:
                raise AssertionError("Prepared Plugin update mutation is missing")
            try:
                transition = self._desired_state.commit_update(mutation)
            except PluginLifecycleError as exc:
                if exc.code not in _UPDATE_TERMINAL_LEDGER_FAILURE_CODES:
                    raise
                result = PluginUpdateOperationResultV2.failed(error_code=exc.code)
            else:
                self._handoff_retirement(transition)
                if (
                    transition.previous_state.selection.desired_state
                    == "installed_enabled"
                ):
                    changed = changed_package_fields(
                        command.expected_package_revision,
                        command.staged_package_revision,
                    )
                    result = PluginUpdateOperationResultV2.restart_required(
                        transition=transition,
                        restart_requirement=PluginUpdateRestartRequirementV1(
                            changed_package_fields=changed
                        ),
                    )
                else:
                    result = PluginUpdateOperationResultV2.succeeded(
                        transition=transition
                    )

        terminal = PluginUpdateOperationEventV2.terminal(
            journal_revision=journal_revision + 1,
            command=command,
            migration_fence=fence,
            result=result,
        )
        self._append_unlocked(terminal)
        return terminal

    def _handoff_retirement(
        self,
        transition: PluginDesiredStateJournalTransition,
    ) -> None:
        self._retirement_intents.request_for(transition)

    def _prepare_update_mutation(
        self,
        command: PluginManagementUpdateCommandV2,
        fence: PluginMigrationFenceV1,
    ) -> tuple[PluginDesiredStateUpdateMutationV1 | None, str | None]:
        snapshot = self._desired_state.snapshot()
        if snapshot.inventory_revision != command.expected_inventory_revision:
            for transition in self._desired_state.transitions():
                if transition.mutation.operation_id != command.operation_id:
                    continue
                if (
                    isinstance(transition, PluginDesiredStateUpdateTransitionV2)
                    and transition.mutation.command == command
                    and transition.mutation.migration_fence == fence
                ):
                    return transition.mutation, None
                raise _corrupt(
                    self._path,
                    "Plugin update operation conflicts with desired-state evidence",
                )
            return None, "plugin_inventory_revision_conflict"
        installation = snapshot.installation(command.installation_key)
        selection = installation.selection
        if selection.desired_state == "absent":
            return None, "plugin_update_not_installed"
        if selection.package_revision != command.expected_package_revision:
            return None, "plugin_update_expected_package_mismatch"
        if command.staged_package_revision == command.expected_package_revision:
            return None, "plugin_update_target_not_new"
        return (
            PluginDesiredStateUpdateMutationV1(
                command=command,
                desired_state=selection.desired_state,
                migration_fence=fence,
            ),
            None,
        )

    def _command_state_error(
        self,
        command: PluginManagementCommandV1,
    ) -> str | None:
        snapshot = self._desired_state.snapshot()
        if snapshot.inventory_revision != command.mutation.expected_inventory_revision:
            return None
        installation = snapshot.installation(command.mutation.installation_key)
        if (
            command.action == "install"
            and installation.selection.desired_state == "installed_enabled"
        ):
            return "plugin_installation_already_enabled"
        return None

    def _existing_operation(
        self,
        replayed: _ReplayedOperations,
        command: PluginManagementCommand,
    ) -> PluginManagementOperationEvent | None:
        operation_for_key = replayed.operation_by_idempotency.get(
            command.idempotency_key
        )
        if operation_for_key is not None:
            event = replayed.latest_by_operation[operation_for_key]
            if event.command != command:
                raise PluginManagementError(
                    "Plugin management idempotency key was reused",
                    code="plugin_management_idempotency_conflict",
                    path=self._path,
                )
            return event
        by_operation = replayed.latest_by_operation.get(command.operation_id)
        if by_operation is not None:
            if by_operation.command != command:
                raise PluginManagementError(
                    "Plugin management operation id was reused",
                    code="plugin_management_operation_conflict",
                    path=self._path,
                )
            return by_operation
        return None

    def _reject_busy_installation(
        self,
        replayed: _ReplayedOperations,
        key: PluginInstallationKeyV1,
    ) -> None:
        if any(
            event.status != "terminal"
            and _installation_key(event.command) == key
            for event in replayed.latest_by_operation.values()
        ):
            raise PluginManagementError(
                "Plugin Installation has an incomplete management operation",
                code="plugin_management_installation_busy",
                path=self._path,
            )

    def _load_and_replay_unlocked(self) -> _ReplayedOperations:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginManagementOperationEvent] = (
                load_jsonl(
                    self._path,
                    record_codec=PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_management_record",
                    "unsupported_plugin_management_record_version",
                }
                else "plugin_management_journal_corrupt"
            )
            raise PluginManagementError(
                "Plugin management operation journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        replayed = _replay(snapshot.records, path=self._path)
        self._validate_terminal_results(replayed)
        return replayed

    def _append_unlocked(self, event: PluginManagementOperationEvent) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_MANAGEMENT_OPERATION_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _validate_terminal_results(self, replayed: _ReplayedOperations) -> None:
        desired_by_operation = {
            transition.mutation.operation_id: transition
            for transition in self._desired_state.transitions()
        }
        retirement_snapshot = self._retirement_intents.snapshot()
        retirement_by_operation = {
            intent.source_operation_id: intent
            for intent in retirement_snapshot.intents
        }
        for operation_id, intent in retirement_by_operation.items():
            if desired_by_operation.get(operation_id) != intent.source_transition:
                raise _retirement_corrupt(
                    self._retirement_intents.path,
                    "Plugin retirement intent is not present in desired state",
                )
        for event in replayed.latest_by_operation.values():
            if event.status != "terminal" or event.result is None:
                continue
            desired = desired_by_operation.get(event.command.operation_id)
            if isinstance(event, PluginManagementOperationEventV1):
                committed = event.result.disposition == "succeeded"
            else:
                committed = event.result.disposition in {
                    "succeeded",
                    "restart_required",
                }
            if committed and desired != event.result.transition:
                raise _corrupt(
                    self._path,
                    "Plugin management success is not present in desired state",
                )
            if not committed and desired is not None:
                raise _corrupt(
                    self._path,
                    "Plugin management failure conflicts with desired state",
                )
            expected_retirement = (
                None if desired is None else retirement_intent_for_transition(desired)
            )
            actual_retirement = retirement_by_operation.get(
                event.command.operation_id
            )
            if committed and actual_retirement != expected_retirement:
                raise _retirement_corrupt(
                    self._retirement_intents.path,
                    "Plugin management terminal result lacks exact retirement intent",
                )
            if not committed and actual_retirement is not None:
                raise _retirement_corrupt(
                    self._retirement_intents.path,
                    "Plugin management failure conflicts with retirement intent",
                )


def _empty_replay() -> _ReplayedOperations:
    return _ReplayedOperations(
        events=(),
        latest_by_operation={},
        operation_by_idempotency={},
        accepted_journal_revision={},
    )


def _replay(
    events: tuple[PluginManagementOperationEvent, ...],
    *,
    path: Path,
) -> _ReplayedOperations:
    replayed = _empty_replay()
    for expected_journal_revision, event in enumerate(events, start=1):
        command = event.command
        operation_id = command.operation_id
        if event.journal_revision != expected_journal_revision:
            raise _corrupt(path, "Plugin management journal revision is not contiguous")
        previous = replayed.latest_by_operation.get(operation_id)
        if previous is None:
            if event.status != "accepted":
                raise _corrupt(path, "Plugin management operation must begin accepted")
            existing_operation = replayed.operation_by_idempotency.get(
                command.idempotency_key
            )
            if existing_operation is not None:
                raise _corrupt(
                    path,
                    "Plugin management idempotency key belongs to two operations",
                )
            replayed.operation_by_idempotency[command.idempotency_key] = operation_id
            replayed.accepted_journal_revision[operation_id] = event.journal_revision
        else:
            if event.command != previous.command:
                raise _corrupt(
                    path, "Plugin management command changed during operation"
                )
            if previous.status == "terminal":
                raise _corrupt(
                    path, "Plugin management operation continued after terminal"
                )
            if event.operation_revision != previous.operation_revision + 1:
                raise _corrupt(
                    path, "Plugin management operation state is not contiguous"
                )
        replayed.latest_by_operation[operation_id] = event
    replayed.events = events
    return replayed


def _corrupt(path: Path, message: str) -> PluginManagementError:
    return PluginManagementError(
        message,
        code="plugin_management_journal_corrupt",
        path=path,
    )


def _retirement_corrupt(path: Path, message: str) -> PluginRetirementError:
    return PluginRetirementError(
        message,
        code="plugin_retirement_journal_corrupt",
        path=path,
    )


def _installation_key(
    command: PluginManagementCommand,
) -> PluginInstallationKeyV1:
    if isinstance(command, PluginManagementCommandV1):
        return command.mutation.installation_key
    return command.installation_key


__all__ = [
    "PluginDesiredStateLedgerPort",
    "PluginManagementError",
    "PluginManagementService",
    "PluginRetirementIntentLedgerPort",
]
