from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

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
    PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginDesiredTransitionKind,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
)
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateMutationV1,
    PluginDesiredStateUpdateTransitionV2,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PluginInstanceIdFactory = Callable[[], str]


class PluginLifecycleError(RuntimeError):
    """Fail-closed desired-state lifecycle error with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class _TransitionRejected(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PluginDesiredStateSnapshotV1:
    inventory_revision: int
    installations: tuple[PluginInstallationStateV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.inventory_revision, int)
            or isinstance(self.inventory_revision, bool)
            or self.inventory_revision < 0
        ):
            raise ValueError("Plugin inventory revision must be non-negative")
        expected = tuple(
            sorted(self.installations, key=lambda item: item.installation_key)
        )
        if self.installations != expected:
            raise ValueError("Plugin installation states must be strictly sorted")
        keys = tuple(item.installation_key for item in self.installations)
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin installation states must be unique")

    def installation(
        self,
        key: PluginInstallationKeyV1,
    ) -> PluginInstallationStateV1:
        for state in self.installations:
            if state.installation_key == key:
                return state
        return PluginInstallationStateV1.initial(key)


@dataclass(slots=True)
class _ReplayedLedger:
    transitions: tuple[PluginDesiredStateJournalTransition, ...]
    states: dict[PluginInstallationKeyV1, PluginInstallationStateV1]
    operations: dict[str, PluginDesiredStateJournalTransition]
    idempotency: dict[str, PluginDesiredStateJournalTransition]
    instance_owners: dict[str, PluginInstallationKeyV1]


class PluginDesiredStateLedger:
    """Durable, inert desired-selection and staged-cutover authority for PLC2.

    This ledger owns only management intent and Instance Revision identity. It
    has no live Plugin, Product Session, Graph, registration, or package-GC
    dependency.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        instance_id_factory: PluginInstanceIdFactory | None = None,
    ) -> None:
        self._path = Path(path)
        self._instance_id_factory = instance_id_factory or _new_instance_id
        self._unlocked_durability = replace(
            DURABLE_LOCKED_JOURNAL,
            locking=False,
        )
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> PluginDesiredStateSnapshotV1:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        return _snapshot(replayed)

    def capture(
        self,
    ) -> tuple[
        PluginDesiredStateSnapshotV1,
        tuple[PluginDesiredStateJournalTransition, ...],
    ]:
        """Capture the snapshot and its exact transition history under one lock."""

        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
        return _snapshot(replayed), replayed.transitions

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            return self._load_and_replay_unlocked().transitions

    def commit(
        self,
        mutation: PluginDesiredStateMutationV1,
    ) -> PluginDesiredStateTransitionV1:
        if not isinstance(mutation, PluginDesiredStateMutationV1):
            raise TypeError("Plugin desired-state mutation is required")
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            repeated = self._repeat_result(replayed, mutation)
            if repeated is not None:
                if not isinstance(repeated, PluginDesiredStateTransitionV1):
                    raise PluginLifecycleError(
                        "Plugin operation identity belongs to an update mutation",
                        code="plugin_management_operation_conflict",
                        path=self._path,
                    )
                return repeated

            head = len(replayed.transitions)
            if mutation.expected_inventory_revision != head:
                raise PluginLifecycleError(
                    "Expected Plugin inventory revision does not match current head",
                    code="plugin_inventory_revision_conflict",
                    path=self._path,
                )

            previous = replayed.states.get(
                mutation.installation_key,
                PluginInstallationStateV1.initial(mutation.installation_key),
            )
            try:
                kind, committed, fresh_instance_id = _apply_mutation(
                    previous,
                    mutation,
                    fresh_instance_id=self._issue_instance_id(
                        replayed.instance_owners,
                        required=_requires_fresh_instance(previous, mutation),
                    ),
                )
            except _TransitionRejected as exc:
                raise PluginLifecycleError(
                    str(exc),
                    code=exc.code,
                    path=self._path,
                ) from exc
            except PluginLifecycleError:
                raise
            except (TypeError, ValueError) as exc:
                raise PluginLifecycleError(
                    f"Invalid Plugin desired-state transition: {exc}",
                    code="invalid_plugin_lifecycle_transition",
                    path=self._path,
                ) from exc
            if fresh_instance_id is not None:
                owner = replayed.instance_owners.get(fresh_instance_id)
                if owner is not None:
                    raise PluginLifecycleError(
                        "Plugin instance identity was already issued",
                        code="plugin_instance_identity_conflict",
                        path=self._path,
                    )

            transition = PluginDesiredStateTransitionV1(
                inventory_revision=head + 1,
                transition_kind=kind,
                mutation=mutation,
                previous_state=previous,
                committed_state=committed,
            )
            append_jsonl_record(
                self._path,
                transition,
                record_codec=PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return transition

    def commit_update(
        self,
        mutation: PluginDesiredStateUpdateMutationV1,
    ) -> PluginDesiredStateUpdateTransitionV2:
        if not isinstance(mutation, PluginDesiredStateUpdateMutationV1):
            raise TypeError("Plugin desired-state update mutation is required")
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            replayed = self._load_and_replay_unlocked()
            repeated = self._repeat_result(replayed, mutation)
            if repeated is not None:
                if not isinstance(repeated, PluginDesiredStateUpdateTransitionV2):
                    raise PluginLifecycleError(
                        "Plugin update operation identity belongs to another mutation",
                        code="plugin_management_operation_conflict",
                        path=self._path,
                    )
                return repeated

            head = len(replayed.transitions)
            if mutation.expected_inventory_revision != head:
                raise PluginLifecycleError(
                    "Expected Plugin inventory revision does not match current head",
                    code="plugin_inventory_revision_conflict",
                    path=self._path,
                )

            previous = replayed.states.get(
                mutation.installation_key,
                PluginInstallationStateV1.initial(mutation.installation_key),
            )
            try:
                committed = _apply_update_mutation(previous, mutation)
            except _TransitionRejected as exc:
                raise PluginLifecycleError(
                    str(exc), code=exc.code, path=self._path
                ) from exc
            except (TypeError, ValueError) as exc:
                raise PluginLifecycleError(
                    f"Invalid Plugin desired-state update transition: {exc}",
                    code="invalid_plugin_lifecycle_transition",
                    path=self._path,
                ) from exc

            transition = PluginDesiredStateUpdateTransitionV2(
                inventory_revision=head + 1,
                mutation=mutation,
                previous_state=previous,
                committed_state=committed,
            )
            append_jsonl_record(
                self._path,
                transition,
                record_codec=PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return transition

    def _load_and_replay_unlocked(self) -> _ReplayedLedger:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginDesiredStateJournalTransition] = (
                load_jsonl(
                    self._path,
                    record_codec=PLUGIN_DESIRED_STATE_JOURNAL_CODEC,
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
                    "invalid_plugin_lifecycle_record",
                    "unsupported_plugin_lifecycle_record_version",
                }
                else "plugin_lifecycle_journal_corrupt"
            )
            raise PluginLifecycleError(
                "Plugin lifecycle journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        return _replay(snapshot.records, path=self._path)

    def _repeat_result(
        self,
        replayed: _ReplayedLedger,
        mutation: PluginDesiredStateMutationV1 | PluginDesiredStateUpdateMutationV1,
    ) -> PluginDesiredStateJournalTransition | None:
        by_idempotency = replayed.idempotency.get(mutation.idempotency_key)
        if by_idempotency is not None:
            if by_idempotency.mutation != mutation:
                raise PluginLifecycleError(
                    "Plugin management idempotency key was reused",
                    code="plugin_management_idempotency_conflict",
                    path=self._path,
                )
            return by_idempotency
        by_operation = replayed.operations.get(mutation.operation_id)
        if by_operation is not None:
            if by_operation.mutation != mutation:
                raise PluginLifecycleError(
                    "Plugin management operation id was reused",
                    code="plugin_management_operation_conflict",
                    path=self._path,
                )
            return by_operation
        return None

    def _issue_instance_id(
        self,
        instance_owners: dict[str, PluginInstallationKeyV1],
        *,
        required: bool,
    ) -> str | None:
        if not required:
            return None
        value = self._instance_id_factory()
        if not isinstance(value, str) or not value:
            raise PluginLifecycleError(
                "Plugin instance identity issuer returned an invalid value",
                code="plugin_instance_identity_conflict",
                path=self._path,
            )
        if value in instance_owners:
            raise PluginLifecycleError(
                "Plugin instance identity issuer returned an existing identity",
                code="plugin_instance_identity_conflict",
                path=self._path,
            )
        return value


def _empty_replay() -> _ReplayedLedger:
    return _ReplayedLedger(
        transitions=(),
        states={},
        operations={},
        idempotency={},
        instance_owners={},
    )


def _replay(
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    path: Path,
) -> _ReplayedLedger:
    replayed = _empty_replay()
    for expected_revision, transition in enumerate(transitions, start=1):
        mutation = transition.mutation
        key = mutation.installation_key
        previous = replayed.states.get(key, PluginInstallationStateV1.initial(key))
        if (
            transition.inventory_revision != expected_revision
            or mutation.expected_inventory_revision != expected_revision - 1
            or transition.previous_state != previous
        ):
            raise _corrupt(path, "Plugin lifecycle journal chain is not contiguous")
        if mutation.operation_id in replayed.operations:
            raise _corrupt(path, "Plugin lifecycle operation id is duplicated")
        if mutation.idempotency_key in replayed.idempotency:
            raise _corrupt(path, "Plugin lifecycle idempotency key is duplicated")

        expected_kind: str
        try:
            if isinstance(transition, PluginDesiredStateTransitionV1):
                normal_mutation = transition.mutation
                committed_instance = (
                    transition.committed_state.selection.instance_revision_ref
                )
                replay_fresh_id = (
                    committed_instance.instance_id
                    if _requires_fresh_instance(previous, normal_mutation)
                    and committed_instance is not None
                    else None
                )
                expected_kind, expected_state, fresh_instance_id = _apply_mutation(
                    previous,
                    normal_mutation,
                    fresh_instance_id=replay_fresh_id,
                )
            else:
                update_mutation = transition.mutation
                expected_kind = "update"
                expected_state = _apply_update_mutation(previous, update_mutation)
                fresh_instance_id = None
        except (TypeError, ValueError) as exc:
            raise _corrupt(
                path, f"Plugin lifecycle transition is invalid: {exc}"
            ) from exc
        if (
            transition.transition_kind != expected_kind
            or transition.committed_state != expected_state
        ):
            raise _corrupt(path, "Plugin lifecycle committed state cannot be replayed")
        if (
            fresh_instance_id is not None
            and fresh_instance_id in replayed.instance_owners
        ):
            raise _corrupt(path, "Plugin instance identity was issued more than once")

        for instance_ref in (
            transition.previous_state.latest_instance_revision_ref,
            transition.committed_state.latest_instance_revision_ref,
        ):
            if instance_ref is None:
                continue
            owner = replayed.instance_owners.setdefault(instance_ref.instance_id, key)
            if owner != key:
                raise _corrupt(
                    path, "Plugin instance identity belongs to two installations"
                )

        replayed.states[key] = transition.committed_state
        replayed.operations[mutation.operation_id] = transition
        replayed.idempotency[mutation.idempotency_key] = transition

    replayed.transitions = transitions
    return replayed


def _apply_mutation(
    previous: PluginInstallationStateV1,
    mutation: PluginDesiredStateMutationV1,
    *,
    fresh_instance_id: str | None,
) -> tuple[
    PluginDesiredTransitionKind,
    PluginInstallationStateV1,
    str | None,
]:
    key = mutation.installation_key
    if previous.installation_key != key:
        raise ValueError("Mutation and previous Installation keys do not match")
    current_selection = previous.selection
    current_state = current_selection.desired_state

    if mutation.desired_state == "absent":
        kind: PluginDesiredTransitionKind = (
            "unchanged" if current_state == "absent" else "remove"
        )
        return (
            kind,
            PluginInstallationStateV1(
                installation_key=key,
                selection=PluginDesiredSelectionV1.absent(),
                latest_instance_revision_ref=previous.latest_instance_revision_ref,
            ),
            None,
        )

    package = mutation.package_revision or current_selection.package_revision
    if package is None:
        raise _TransitionRejected(
            "Installing a Plugin requires a package revision",
            code="invalid_plugin_lifecycle_transition",
        )
    if package.plugin_id != key.plugin_id:
        raise _TransitionRejected(
            "Package revision does not match Installation Plugin id",
            code="plugin_package_revision_mismatch",
        )
    if (
        current_state != "absent"
        and current_selection.package_revision is not None
        and package != current_selection.package_revision
    ):
        raise _TransitionRejected(
            "Package changes require the staged Plugin update path",
            code="plugin_update_requires_staging",
        )

    if mutation.desired_state == "installed_disabled":
        latest = (
            None if current_state == "absent" else previous.latest_instance_revision_ref
        )
        if current_state == "absent":
            kind = "install"
        elif current_state == "installed_enabled":
            kind = "disable"
        else:
            kind = "unchanged"
        return (
            kind,
            PluginInstallationStateV1(
                installation_key=key,
                selection=PluginDesiredSelectionV1(
                    desired_state="installed_disabled",
                    package_revision=package,
                    instance_revision_ref=None,
                ),
                latest_instance_revision_ref=latest,
            ),
            None,
        )

    if current_state == "installed_enabled":
        instance_ref = current_selection.instance_revision_ref
        if instance_ref is None:
            raise ValueError("Enabled predecessor is missing its Instance Revision")
        return (
            "unchanged",
            previous,
            None,
        )

    latest = previous.latest_instance_revision_ref
    issued_fresh: str | None = None
    if current_state == "absent" or latest is None:
        if fresh_instance_id is None:
            raise ValueError("Fresh Plugin Instance identity is required")
        instance_ref = PluginInstanceRevisionRef(
            instance_id=fresh_instance_id,
            plugin_id=key.plugin_id,
            revision=1,
        )
        issued_fresh = fresh_instance_id
    else:
        instance_ref = PluginInstanceRevisionRef(
            instance_id=latest.instance_id,
            plugin_id=key.plugin_id,
            revision=latest.revision + 1,
        )
    return (
        "install" if current_state == "absent" else "enable",
        PluginInstallationStateV1(
            installation_key=key,
            selection=PluginDesiredSelectionV1(
                desired_state="installed_enabled",
                package_revision=package,
                instance_revision_ref=instance_ref,
            ),
            latest_instance_revision_ref=instance_ref,
        ),
        issued_fresh,
    )


def _apply_update_mutation(
    previous: PluginInstallationStateV1,
    mutation: PluginDesiredStateUpdateMutationV1,
) -> PluginInstallationStateV1:
    command = mutation.command
    key = command.installation_key
    if previous.installation_key != key:
        raise ValueError("Update mutation and previous Installation keys do not match")
    current = previous.selection
    if current.desired_state == "absent":
        raise _TransitionRejected(
            "Plugin update requires an installed predecessor",
            code="plugin_update_not_installed",
        )
    if current.desired_state != mutation.desired_state:
        raise ValueError("Plugin update mutation does not preserve desired state")
    if current.package_revision != command.expected_package_revision:
        raise _TransitionRejected(
            "Plugin update predecessor Package Revision does not match",
            code="plugin_update_expected_package_mismatch",
        )
    if command.staged_package_revision == command.expected_package_revision:
        raise _TransitionRejected(
            "Plugin update target must differ from its predecessor",
            code="plugin_update_target_not_new",
        )

    if current.desired_state == "installed_disabled":
        return PluginInstallationStateV1(
            installation_key=key,
            selection=PluginDesiredSelectionV1(
                desired_state="installed_disabled",
                package_revision=command.staged_package_revision,
                instance_revision_ref=None,
            ),
            latest_instance_revision_ref=previous.latest_instance_revision_ref,
        )

    current_instance = current.instance_revision_ref
    latest = previous.latest_instance_revision_ref
    if current_instance is None or latest is None or current_instance != latest:
        raise ValueError("Enabled Plugin update predecessor has invalid Instance lineage")
    next_instance = PluginInstanceRevisionRef(
        instance_id=latest.instance_id,
        plugin_id=latest.plugin_id,
        revision=latest.revision + 1,
    )
    return PluginInstallationStateV1(
        installation_key=key,
        selection=PluginDesiredSelectionV1(
            desired_state="installed_enabled",
            package_revision=command.staged_package_revision,
            instance_revision_ref=next_instance,
        ),
        latest_instance_revision_ref=next_instance,
    )


def _requires_fresh_instance(
    previous: PluginInstallationStateV1,
    mutation: PluginDesiredStateMutationV1,
) -> bool:
    return mutation.desired_state == "installed_enabled" and (
        previous.selection.desired_state == "absent"
        or previous.latest_instance_revision_ref is None
    )


def _snapshot(replayed: _ReplayedLedger) -> PluginDesiredStateSnapshotV1:
    return PluginDesiredStateSnapshotV1(
        inventory_revision=len(replayed.transitions),
        installations=tuple(
            sorted(replayed.states.values(), key=lambda item: item.installation_key)
        ),
    )


def _new_instance_id() -> str:
    return f"plugin-instance-{secrets.token_hex(16)}"


def _corrupt(path: Path, message: str) -> PluginLifecycleError:
    return PluginLifecycleError(
        message,
        code="plugin_lifecycle_journal_corrupt",
        path=path,
    )


__all__ = [
    "PluginDesiredStateLedger",
    "PluginDesiredStateSnapshotV1",
    "PluginInstanceIdFactory",
    "PluginLifecycleError",
]
