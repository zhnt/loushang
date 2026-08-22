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
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
)
from loushang.harness.plugin_management.operations import (
    PLUGIN_MANAGEMENT_OPERATION_EVENT_CODEC,
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

_TERMINAL_LEDGER_FAILURE_CODES = frozenset(
    PLUGIN_MANAGEMENT_TERMINAL_ERROR_CODES - {"plugin_installation_already_enabled"}
)


class PluginDesiredStateLedgerPort(Protocol):
    @property
    def path(self) -> Path: ...

    def commit(
        self,
        mutation: PluginDesiredStateMutationV1,
    ) -> PluginDesiredStateTransitionV1: ...

    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...

    def transitions(self) -> tuple[PluginDesiredStateTransitionV1, ...]: ...


class PluginManagementError(RuntimeError):
    """Fail-closed management-command error with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(slots=True)
class _ReplayedOperations:
    events: tuple[PluginManagementOperationEventV1, ...]
    latest_by_operation: dict[str, PluginManagementOperationEventV1]
    operation_by_idempotency: dict[str, str]
    accepted_journal_revision: dict[str, int]


class PluginManagementService:
    """Sole PLC2-2 command authority over inert Plugin desired state."""

    def __init__(
        self,
        *,
        desired_state: PluginDesiredStateLedgerPort,
        operation_journal_path: str | Path,
    ) -> None:
        self._desired_state = desired_state
        self._path = Path(operation_journal_path)
        if self._path.resolve() == desired_state.path.resolve():
            raise ValueError(
                "Plugin operation and desired-state journals must be distinct"
            )
        self._unlocked_durability = replace(
            DURABLE_LOCKED_JOURNAL,
            locking=False,
        )
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def operation_journal_path(self) -> Path:
        return self._path

    def submit(
        self,
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1:
        if not isinstance(command, PluginManagementCommandV1):
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

            self._reject_busy_installation(replayed, command.mutation.installation_key)
            accepted = PluginManagementOperationEventV1.accepted(
                journal_revision=len(replayed.events) + 1,
                command=command,
            )
            self._append_unlocked(accepted)
            return self._execute_unlocked(
                command,
                latest=accepted,
                journal_revision=accepted.journal_revision,
            )

    def recover(self) -> tuple[PluginManagementOperationEventV1, ...]:
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
            recovered: list[PluginManagementOperationEventV1] = []
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

    def operations(self) -> tuple[PluginManagementOperationEventV1, ...]:
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
    ) -> PluginManagementOperationEventV1 | None:
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
        command: PluginManagementCommandV1,
        *,
        latest: PluginManagementOperationEventV1,
        journal_revision: int,
    ) -> PluginManagementOperationEventV1:
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
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1 | None:
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
            and event.command.mutation.installation_key == key
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
            snapshot: JsonlSnapshot[None, PluginManagementOperationEventV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PLUGIN_MANAGEMENT_OPERATION_EVENT_CODEC,
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

    def _append_unlocked(self, event: PluginManagementOperationEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_MANAGEMENT_OPERATION_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _validate_terminal_results(self, replayed: _ReplayedOperations) -> None:
        desired_by_operation = {
            transition.mutation.operation_id: transition
            for transition in self._desired_state.transitions()
        }
        for event in replayed.latest_by_operation.values():
            if event.status != "terminal" or event.result is None:
                continue
            desired = desired_by_operation.get(event.command.operation_id)
            if event.result.disposition == "succeeded":
                if desired != event.result.transition:
                    raise _corrupt(
                        self._path,
                        "Plugin management success is not present in desired state",
                    )
            elif desired is not None:
                raise _corrupt(
                    self._path,
                    "Plugin management failure conflicts with desired state",
                )


def _empty_replay() -> _ReplayedOperations:
    return _ReplayedOperations(
        events=(),
        latest_by_operation={},
        operation_by_idempotency={},
        accepted_journal_revision={},
    )


def _replay(
    events: tuple[PluginManagementOperationEventV1, ...],
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
            expected_status = {
                "accepted": "running",
                "running": "terminal",
                "terminal": None,
            }[previous.status]
            if event.status != expected_status:
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


__all__ = [
    "PluginDesiredStateLedgerPort",
    "PluginManagementError",
    "PluginManagementService",
]
