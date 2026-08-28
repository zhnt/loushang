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
from loushang.harness.plugin_management.instance_records import (
    PLUGIN_INSTANCE_RUNTIME_EVENT_CODEC,
    PluginInstanceActivationV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceLeaseKind,
    PluginInstanceRetirementCompletionV1,
    PluginInstanceRevocationV1,
    PluginInstanceRuntimeEventV1,
    PluginInstanceRuntimeState,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentSnapshotV1,
    PluginRetirementIntentV1,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetInventorySnapshotV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

_ROOT_ACQUISITION_KINDS = frozenset(
    {"independent", "owner_generation", "session_membership"}
)


def plugin_instance_security_acceptance_journal_path(
    runtime_path: str | Path,
) -> Path:
    """Derive the one canonical security-acceptance journal for a runtime."""

    canonical = Path(runtime_path).resolve()
    if canonical.suffix:
        name = f"{canonical.stem}.security-acceptances{canonical.suffix}"
    else:
        name = f"{canonical.name}.security-acceptances.jsonl"
    return canonical.with_name(name)


class PluginInstanceDesiredStateSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]: ...


class PluginInstanceRetirementIntentSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginRetirementIntentSnapshotV1: ...


class PluginInstanceRetirementSetSourcePort(Protocol):
    @property
    def path(self) -> Path: ...

    def snapshot(self) -> PluginRetirementSetInventorySnapshotV1: ...


class PluginInstanceSecurityAcceptanceSourcePort(Protocol):
    """Durable security acceptances that bar new runtime acquisition."""

    @property
    def path(self) -> Path: ...

    def accepted_revocations(self) -> tuple[PluginInstanceRevocationV1, ...]: ...


class PluginInstanceRuntimeError(RuntimeError):
    """Fail-closed Plugin Instance runtime failure with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginInstanceRuntimeSnapshotV1:
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    activation: PluginInstanceActivationV1
    state: PluginInstanceRuntimeState
    retirement_intent: PluginRetirementIntentV1 | None
    revocation: PluginInstanceRevocationV1 | None
    completion: PluginInstanceRetirementCompletionV1 | None
    open_family_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.activation.installation_key != self.installation_key
            or self.activation.instance_revision_ref != self.instance_revision_ref
            or self.activation.package_revision != self.package_revision
        ):
            raise ValueError("Plugin Instance runtime activation does not match")
        if self.open_family_ids != tuple(sorted(self.open_family_ids)) or len(
            self.open_family_ids
        ) != len(set(self.open_family_ids)):
            raise ValueError(
                "Plugin Instance open family ids must be sorted and unique"
            )
        if self.state == "ACTIVE":
            if any(
                item is not None
                for item in (
                    self.retirement_intent,
                    self.revocation,
                    self.completion,
                )
            ):
                raise ValueError("ACTIVE Plugin Instance has terminal evidence")
        elif self.state == "DRAINING":
            if (
                self.retirement_intent is None
                or self.revocation is not None
                or self.completion is not None
            ):
                raise ValueError("DRAINING Plugin Instance evidence is incomplete")
        elif self.state == "REVOKING":
            if self.revocation is None or self.completion is not None:
                raise ValueError("REVOKING Plugin Instance evidence is incomplete")
        elif self.state == "RETIRED":
            if self.completion is None or self.open_family_ids:
                raise ValueError("RETIRED Plugin Instance evidence is incomplete")
            if self.completion.completion_kind == "graceful" and (
                self.retirement_intent is None or self.revocation is not None
            ):
                raise ValueError(
                    "Graceful retirement requires an intent without revocation"
                )
            if (
                self.completion.completion_kind == "security"
                and self.revocation is None
            ):
                raise ValueError("Security retirement requires a revocation")
        else:
            raise ValueError("Unsupported Plugin Instance runtime state")

    @property
    def open_lease_count(self) -> int:
        return len(self.open_family_ids)


@dataclass(frozen=True, slots=True)
class PluginInstanceRuntimeInventorySnapshotV1:
    journal_revision: int
    instances: tuple[PluginInstanceRuntimeSnapshotV1, ...]
    open_families: tuple[PluginInstanceLeaseFamilyV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.journal_revision, int)
            or isinstance(self.journal_revision, bool)
            or self.journal_revision < 0
        ):
            raise ValueError("Plugin Instance runtime revision must be non-negative")
        if self.instances != tuple(
            sorted(self.instances, key=_instance_snapshot_sort_key)
        ):
            raise ValueError("Plugin Instance runtime snapshots must be sorted")
        refs = tuple(item.instance_revision_ref for item in self.instances)
        if len(refs) != len(set(refs)):
            raise ValueError("Plugin Instance runtime snapshots must be unique")
        if self.open_families != tuple(
            sorted(self.open_families, key=lambda item: item.family_id)
        ):
            raise ValueError("Open Plugin Instance families must be sorted")
        family_ids = tuple(item.family_id for item in self.open_families)
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("Open Plugin Instance families must be unique")
        expected_membership: dict[PluginInstanceRevisionRef, set[str]] = {}
        for family in self.open_families:
            for member in family.members:
                expected_membership.setdefault(member.instance_revision_ref, set()).add(
                    family.family_id
                )
        for instance in self.instances:
            if instance.open_family_ids != tuple(
                sorted(expected_membership.get(instance.instance_revision_ref, set()))
            ):
                raise ValueError("Plugin Instance family membership is inconsistent")
        if set(expected_membership) - set(refs):
            raise ValueError("Open family references an unknown Plugin Instance")

    def instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> PluginInstanceRuntimeSnapshotV1 | None:
        for instance in self.instances:
            if instance.instance_revision_ref == instance_revision_ref:
                return instance
        return None

    def family(self, family_id: str) -> PluginInstanceLeaseFamilyV1 | None:
        for family in self.open_families:
            if family.family_id == family_id:
                return family
        return None


@dataclass(slots=True)
class _MutableInstance:
    activation: PluginInstanceActivationV1
    state: PluginInstanceRuntimeState
    retirement_intent: PluginRetirementIntentV1 | None
    revocation: PluginInstanceRevocationV1 | None
    completion: PluginInstanceRetirementCompletionV1 | None
    open_family_ids: set[str]


@dataclass(slots=True)
class _MutableFamily:
    family: PluginInstanceLeaseFamilyV1
    release: PluginInstanceLeaseFamilyReleaseV1 | None


@dataclass(slots=True)
class _ReplayedInstanceRuntime:
    events: list[PluginInstanceRuntimeEventV1]
    instances: dict[PluginInstanceRevisionRef, _MutableInstance]
    families: dict[str, _MutableFamily]
    operation_events: dict[str, PluginInstanceRuntimeEventV1]
    idempotency_events: dict[str, PluginInstanceRuntimeEventV1]
    activation_ids: dict[str, PluginInstanceActivationV1]
    revocation_ids: dict[str, PluginInstanceRevocationV1]
    completion_ids: dict[str, PluginInstanceRetirementCompletionV1]


@dataclass(frozen=True, slots=True)
class _SourceEvidence:
    desired_snapshot: PluginDesiredStateSnapshotV1
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...]
    retirement_intents: PluginRetirementIntentSnapshotV1
    retirement_sets: PluginRetirementSetInventorySnapshotV1


class PluginInstanceRuntimeLedger:
    """Durable Product-host authority for Plugin Instance state and leases."""

    def __init__(
        self,
        path: str | Path,
        *,
        management_operation_journal_path: str | Path,
        desired_state: PluginInstanceDesiredStateSourcePort,
        retirement_intents: PluginInstanceRetirementIntentSourcePort,
        retirement_sets: PluginInstanceRetirementSetSourcePort,
        security_acceptances: PluginInstanceSecurityAcceptanceSourcePort,
    ) -> None:
        # Lock sidecars are derived from these stored paths, so normalize once
        # before any equality check or cross-process operation gate is used.
        self._path = Path(path).resolve()
        self._operation_path = Path(management_operation_journal_path).resolve()
        self._desired_state = desired_state
        self._retirement_intents = retirement_intents
        self._retirement_sets = retirement_sets
        self._validate_security_acceptance_source(security_acceptances)
        self._security_acceptances = security_acceptances
        journal_paths = {
            self._path.resolve(),
            self._operation_path.resolve(),
            desired_state.path.resolve(),
            retirement_intents.path.resolve(),
            retirement_sets.path.resolve(),
            security_acceptances.path.resolve(),
        }
        if len(journal_paths) != 6:
            raise ValueError("Plugin Instance runtime journals must be distinct")
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def management_operation_journal_path(self) -> Path:
        return self._operation_path

    @property
    def security_acceptance_journal_path(self) -> Path:
        return plugin_instance_security_acceptance_journal_path(self._path)

    def bind_security_acceptance_source(
        self,
        source: PluginInstanceSecurityAcceptanceSourcePort,
    ) -> None:
        """Seal the one write-ahead security barrier before runtime service."""

        self._validate_security_acceptance_source(source)
        existing = self._security_acceptances
        if existing is source or existing.path == source.path:
            return
        raise RuntimeError("Plugin Instance security acceptance source is sealed")

    def _validate_security_acceptance_source(
        self,
        source: PluginInstanceSecurityAcceptanceSourcePort,
    ) -> None:
        path = getattr(source, "path", None)
        if not isinstance(path, Path) or not callable(
            getattr(source, "accepted_revocations", None)
        ):
            raise TypeError("Plugin Instance security acceptance source is invalid")
        expected = plugin_instance_security_acceptance_journal_path(self._path)
        if path != path.resolve() or path != expected:
            raise ValueError(
                "Plugin Instance security acceptance source must use its canonical path"
            )

    def activate_current(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        operation_id: str,
        idempotency_key: str,
        direct_host_reference: str,
    ) -> PluginInstanceRuntimeSnapshotV1:
        if not isinstance(installation_key, PluginInstallationKeyV1):
            raise TypeError("Plugin Installation key is required")
        _require_nonempty(operation_id, name="activation operation id")
        _require_nonempty(idempotency_key, name="activation idempotency key")
        _require_nonempty(direct_host_reference, name="direct host reference")
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                )
                if repeated is not None:
                    activation = repeated.activation
                    if (
                        activation is None
                        or activation.installation_key != installation_key
                        or activation.direct_host_family.holder_reference
                        != direct_host_reference
                    ):
                        raise _conflict(
                            self._path,
                            "Plugin Instance activation identity was reused",
                        )
                    self._require_not_security_accepted(
                        (activation.instance_revision_ref,)
                    )
                    return _snapshot_instance(
                        replayed.instances[activation.instance_revision_ref]
                    )
                installation = sources.desired_snapshot.installation(installation_key)
                selection = installation.selection
                if (
                    selection.desired_state != "installed_enabled"
                    or selection.instance_revision_ref is None
                    or selection.package_revision is None
                ):
                    raise _unavailable(
                        self._path,
                        "Plugin Installation has no current enabled Instance",
                    )
                self._require_not_security_accepted((selection.instance_revision_ref,))
                if selection.instance_revision_ref in replayed.instances:
                    raise _transition_error(
                        self._path,
                        "Current Plugin Instance Revision is already activated",
                    )
                if any(
                    current.activation.installation_key == installation_key
                    and current.state == "ACTIVE"
                    for current in replayed.instances.values()
                ):
                    raise _transition_error(
                        self._path,
                        "Plugin Installation already has an ACTIVE revision",
                    )
                activation = PluginInstanceActivationV1.create(
                    installation_key=installation_key,
                    instance_revision_ref=selection.instance_revision_ref,
                    package_revision=selection.package_revision,
                    source_inventory_revision=sources.desired_snapshot.inventory_revision,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    direct_host_reference=direct_host_reference,
                )
                event = PluginInstanceRuntimeEventV1.activated(
                    journal_revision=len(replayed.events) + 1,
                    activation=activation,
                )
                self._append_and_apply_unlocked(replayed, event)
                return _snapshot_instance(
                    replayed.instances[activation.instance_revision_ref]
                )

    def acquire_current_family(
        self,
        installation_keys: tuple[PluginInstallationKeyV1, ...],
        *,
        lease_kind: PluginInstanceLeaseKind,
        operation_id: str,
        idempotency_key: str,
        holder_reference: str,
    ) -> PluginInstanceLeaseFamilyV1:
        if lease_kind not in _ROOT_ACQUISITION_KINDS:
            raise ValueError("Unsupported root Plugin Instance lease kind")
        keys = _canonical_installation_keys(installation_keys)
        if lease_kind in {"independent", "owner_generation"} and len(keys) != 1:
            raise ValueError("Plugin Instance lease kind requires one Installation")
        for value, name in (
            (operation_id, "lease operation id"),
            (idempotency_key, "lease idempotency key"),
            (holder_reference, "lease holder reference"),
        ):
            _require_nonempty(value, name=name)
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                )
                if repeated is not None:
                    family = repeated.family
                    if (
                        family is None
                        or family.lease_kind != lease_kind
                        or family.holder_reference != holder_reference
                        or tuple(member.installation_key for member in family.members)
                        != keys
                        or family.parent_family_id is not None
                    ):
                        raise _conflict(
                            self._path,
                            "Plugin Instance acquisition identity was reused",
                        )
                    if replayed.families[family.family_id].release is not None:
                        raise _transition_error(
                            self._path,
                            "Plugin Instance acquisition was already released",
                        )
                    self._require_not_security_accepted(
                        tuple(member.instance_revision_ref for member in family.members)
                    )
                    return family
                subjects = tuple(
                    self._current_active_subject(
                        replayed,
                        sources.desired_snapshot,
                        installation_key,
                    )
                    for installation_key in keys
                )
                family = PluginInstanceLeaseFamilyV1.create(
                    lease_kind=lease_kind,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    holder_reference=holder_reference,
                    parent_family_id=None,
                    source_inventory_revision=sources.desired_snapshot.inventory_revision,
                    member_subjects=subjects,
                )
                if family.family_id in replayed.families:
                    raise _conflict(
                        self._path,
                        "Plugin Instance lease family id was reused",
                    )
                event = PluginInstanceRuntimeEventV1.family_acquired(
                    journal_revision=len(replayed.events) + 1,
                    family=family,
                )
                self._append_and_apply_unlocked(replayed, event)
                return family

    def derive_agent_membership(
        self,
        parent_family_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
        holder_reference: str,
    ) -> PluginInstanceLeaseFamilyV1:
        _require_sha256(parent_family_id, name="parent family id")
        for value, name in (
            (operation_id, "lease operation id"),
            (idempotency_key, "lease idempotency key"),
            (holder_reference, "lease holder reference"),
        ):
            _require_nonempty(value, name=name)
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                )
                if repeated is not None:
                    family = repeated.family
                    if (
                        family is None
                        or family.lease_kind != "agent_membership"
                        or family.parent_family_id != parent_family_id
                        or family.holder_reference != holder_reference
                    ):
                        raise _conflict(
                            self._path,
                            "Plugin Instance derivation identity was reused",
                        )
                    if replayed.families[family.family_id].release is not None:
                        raise _transition_error(
                            self._path,
                            "Plugin Instance derivation was already released",
                        )
                    self._require_not_security_accepted(
                        tuple(member.instance_revision_ref for member in family.members)
                    )
                    return family
                parent = replayed.families.get(parent_family_id)
                if (
                    parent is None
                    or parent.release is not None
                    or parent.family.lease_kind
                    not in {"session_membership", "agent_membership"}
                ):
                    raise _transition_error(
                        self._path,
                        "Agent membership requires an open membership parent",
                    )
                self._require_not_security_accepted(
                    tuple(
                        member.instance_revision_ref for member in parent.family.members
                    )
                )
                subjects = tuple(
                    (
                        member.installation_key,
                        member.instance_revision_ref,
                        member.package_revision,
                    )
                    for member in parent.family.members
                )
                if any(
                    replayed.instances[instance_ref].state not in {"ACTIVE", "DRAINING"}
                    for _, instance_ref, _ in subjects
                ):
                    raise _transition_error(
                        self._path,
                        "Parent membership cannot derive in current Instance state",
                    )
                family = PluginInstanceLeaseFamilyV1.create(
                    lease_kind="agent_membership",
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    holder_reference=holder_reference,
                    parent_family_id=parent_family_id,
                    source_inventory_revision=None,
                    member_subjects=subjects,
                )
                if family.family_id in replayed.families:
                    raise _conflict(
                        self._path,
                        "Plugin Instance lease family id was reused",
                    )
                event = PluginInstanceRuntimeEventV1.family_acquired(
                    journal_revision=len(replayed.events) + 1,
                    family=family,
                )
                self._append_and_apply_unlocked(replayed, event)
                return family

    def begin_drain(
        self,
        retirement_intent: PluginRetirementIntentV1,
    ) -> PluginInstanceRuntimeSnapshotV1:
        if not isinstance(retirement_intent, PluginRetirementIntentV1):
            raise TypeError("Plugin retirement intent is required")
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            source_intent = _intent_by_id(sources).get(retirement_intent.retirement_id)
            retirement_set = sources.retirement_sets.retirement_set(
                retirement_intent.retirement_id
            )
            if (
                source_intent != retirement_intent
                or retirement_set is None
                or retirement_set.intent != retirement_intent
            ):
                raise _corrupt(
                    self._path,
                    "Plugin Instance drain lacks exact retirement evidence",
                )
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                current = replayed.instances.get(
                    retirement_intent.instance_revision_ref
                )
                if current is None:
                    raise _transition_error(
                        self._path,
                        "Retirement intent cannot manufacture Instance activation",
                    )
                if current.retirement_intent is not None:
                    if current.retirement_intent != retirement_intent:
                        raise _conflict(
                            self._path,
                            "Plugin Instance retirement intent was replaced",
                        )
                    return _snapshot_instance(current)
                if current.state != "ACTIVE":
                    raise _transition_error(
                        self._path,
                        "Only an ACTIVE Plugin Instance can begin graceful drain",
                    )
                event = PluginInstanceRuntimeEventV1.drain_started(
                    journal_revision=len(replayed.events) + 1,
                    retirement_intent=retirement_intent,
                )
                self._append_and_apply_unlocked(replayed, event)
                return _snapshot_instance(current)

    def begin_revoke(
        self,
        revocation: PluginInstanceRevocationV1,
    ) -> PluginInstanceRuntimeSnapshotV1:
        """Enter REVOKING through the ordinary Product-host authority."""

        return self._begin_security_revocation(revocation)

    def apply_accepted_security_revocations(
        self,
        revocations: tuple[PluginInstanceRevocationV1, ...],
    ) -> tuple[PluginInstanceRuntimeSnapshotV1, ...]:
        """Recover exact write-ahead security acceptances through this host."""

        if not revocations or any(
            not isinstance(item, PluginInstanceRevocationV1) for item in revocations
        ):
            raise TypeError("Accepted Plugin Instance revocations are required")
        if len(revocations) != len(set(revocations)):
            raise ValueError("Accepted Plugin Instance revocations must be unique")
        accepted = set(self._security_acceptances.accepted_revocations())
        if any(item not in accepted for item in revocations):
            raise _unavailable(
                self._path,
                "Plugin Instance security revocation was not durably accepted",
            )
        return tuple(self._begin_security_revocation(item) for item in revocations)

    def _begin_security_revocation(
        self,
        revocation: PluginInstanceRevocationV1,
    ) -> PluginInstanceRuntimeSnapshotV1:
        if not isinstance(revocation, PluginInstanceRevocationV1):
            raise TypeError("Plugin Instance revocation is required")
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=revocation.operation_id,
                    idempotency_key=revocation.idempotency_key,
                )
                if repeated is not None:
                    if repeated.revocation != revocation:
                        raise _conflict(
                            self._path,
                            "Plugin Instance revocation identity was reused",
                        )
                    repeated_instance = replayed.instances[
                        revocation.instance_revision_ref
                    ]
                    return _snapshot_instance(repeated_instance)
                current = replayed.instances.get(revocation.instance_revision_ref)
                if (
                    current is None
                    or current.activation.installation_key
                    != revocation.installation_key
                ):
                    raise _transition_error(
                        self._path,
                        "Plugin Instance revocation requires activation",
                    )
                if current.state not in {"ACTIVE", "DRAINING"}:
                    raise _transition_error(
                        self._path,
                        "Plugin Instance cannot enter REVOKING from current state",
                    )
                event = PluginInstanceRuntimeEventV1.revoke_started(
                    journal_revision=len(replayed.events) + 1,
                    revocation=revocation,
                )
                self._append_and_apply_unlocked(replayed, event)
                return _snapshot_instance(current)

    def release_family(
        self,
        release: PluginInstanceLeaseFamilyReleaseV1,
    ) -> PluginInstanceLeaseFamilyReleaseV1:
        if not isinstance(release, PluginInstanceLeaseFamilyReleaseV1):
            raise TypeError("Plugin Instance lease family release is required")
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=release.operation_id,
                    idempotency_key=release.idempotency_key,
                )
                if repeated is not None:
                    if repeated.release != release:
                        raise _conflict(
                            self._path,
                            "Plugin Instance release identity was reused",
                        )
                    return release
                family = replayed.families.get(release.family_id)
                if family is None:
                    raise _transition_error(
                        self._path,
                        "Plugin Instance lease family does not exist",
                    )
                if family.release is not None:
                    raise _conflict(
                        self._path,
                        "Plugin Instance lease family has different release evidence",
                    )
                if any(
                    candidate.release is None
                    and candidate.family.parent_family_id == release.family_id
                    for candidate in replayed.families.values()
                ):
                    raise _transition_error(
                        self._path,
                        "Plugin Instance parent family has an open child",
                    )
                if family.family.lease_kind == "direct_host" and any(
                    replayed.instances[member.instance_revision_ref].state == "ACTIVE"
                    for member in family.family.members
                ):
                    raise _transition_error(
                        self._path,
                        "ACTIVE Plugin Instance cannot release its direct host",
                    )
                event = PluginInstanceRuntimeEventV1.family_released(
                    journal_revision=len(replayed.events) + 1,
                    release=release,
                )
                self._append_and_apply_unlocked(replayed, event)
                return release

    def complete_retirement(
        self,
        completion: PluginInstanceRetirementCompletionV1,
    ) -> PluginInstanceRuntimeSnapshotV1:
        if not isinstance(completion, PluginInstanceRetirementCompletionV1):
            raise TypeError("Plugin Instance retirement completion is required")
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                repeated = self._existing_operation(
                    replayed,
                    operation_id=completion.operation_id,
                    idempotency_key=completion.idempotency_key,
                )
                if repeated is not None:
                    if repeated.completion != completion:
                        raise _conflict(
                            self._path,
                            "Plugin Instance completion identity was reused",
                        )
                    return _snapshot_instance(
                        replayed.instances[completion.instance_revision_ref]
                    )
                current = replayed.instances.get(completion.instance_revision_ref)
                if (
                    current is None
                    or current.activation.installation_key
                    != completion.installation_key
                ):
                    raise _transition_error(
                        self._path,
                        "Plugin Instance completion requires activation",
                    )
                if current.open_family_ids:
                    raise _transition_error(
                        self._path,
                        "Plugin Instance retirement is blocked by open leases",
                    )
                if completion.completion_kind == "graceful":
                    intent = current.retirement_intent
                    retirement_set = sources.retirement_sets.retirement_set(
                        completion.coordination_id
                    )
                    if (
                        current.state != "DRAINING"
                        or intent is None
                        or intent.retirement_id != completion.coordination_id
                        or retirement_set is None
                        or retirement_set.intent != intent
                        or retirement_set.state != "succeeded"
                    ):
                        raise _transition_error(
                            self._path,
                            "Graceful Plugin Instance retirement is not ready",
                        )
                else:
                    revocation = current.revocation
                    if (
                        current.state != "REVOKING"
                        or revocation is None
                        or revocation.revocation_id != completion.coordination_id
                    ):
                        raise _transition_error(
                            self._path,
                            "Security Plugin Instance retirement is not ready",
                        )
                event = PluginInstanceRuntimeEventV1.retired(
                    journal_revision=len(replayed.events) + 1,
                    completion=completion,
                )
                self._append_and_apply_unlocked(replayed, event)
                return _snapshot_instance(current)

    def snapshot(self) -> PluginInstanceRuntimeInventorySnapshotV1:
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                return _snapshot_inventory(replayed)

    def events(self) -> tuple[PluginInstanceRuntimeEventV1, ...]:
        with journal_file_lock(
            self._operation_path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            sources = self._load_sources()
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                replayed = self._load_and_replay_unlocked()
                self._validate_sources(replayed, sources)
                return tuple(replayed.events)

    def _current_active_subject(
        self,
        replayed: _ReplayedInstanceRuntime,
        desired_snapshot: PluginDesiredStateSnapshotV1,
        installation_key: PluginInstallationKeyV1,
    ) -> tuple[
        PluginInstallationKeyV1,
        PluginInstanceRevisionRef,
        PluginPackageRevisionRefV1,
    ]:
        selection = desired_snapshot.installation(installation_key).selection
        instance_ref = selection.instance_revision_ref
        package_revision = selection.package_revision
        if (
            selection.desired_state != "installed_enabled"
            or instance_ref is None
            or package_revision is None
        ):
            raise _unavailable(
                self._path,
                "Plugin Installation has no current enabled Instance",
            )
        current = replayed.instances.get(instance_ref)
        self._require_not_security_accepted((instance_ref,))
        if current is None or current.state != "ACTIVE":
            raise _unavailable(
                self._path,
                "Current Plugin Instance cannot serve a new acquisition",
            )
        if current.activation.package_revision != package_revision:
            raise _corrupt(
                self._path,
                "Current Plugin Instance Package Revision is inconsistent",
            )
        return installation_key, instance_ref, package_revision

    def _require_not_security_accepted(
        self,
        instance_revision_refs: tuple[PluginInstanceRevisionRef, ...],
    ) -> None:
        source = self._security_acceptances
        accepted = {
            item.instance_revision_ref for item in source.accepted_revocations()
        }
        if accepted.intersection(instance_revision_refs):
            raise _unavailable(
                self._path,
                "Plugin Instance has a durable security acceptance",
            )

    def _existing_operation(
        self,
        replayed: _ReplayedInstanceRuntime,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PluginInstanceRuntimeEventV1 | None:
        by_operation = replayed.operation_events.get(operation_id)
        by_idempotency = replayed.idempotency_events.get(idempotency_key)
        if by_operation is None and by_idempotency is None:
            return None
        if by_operation is None or by_idempotency is None:
            raise _conflict(
                self._path,
                "Plugin Instance operation identity was partially reused",
            )
        if by_operation is not by_idempotency:
            raise _conflict(
                self._path,
                "Plugin Instance operation and idempotency identities diverge",
            )
        return by_operation

    def _load_sources(self) -> _SourceEvidence:
        return _SourceEvidence(
            desired_snapshot=self._desired_state.snapshot(),
            desired_transitions=self._desired_state.transitions(),
            retirement_intents=self._retirement_intents.snapshot(),
            retirement_sets=self._retirement_sets.snapshot(),
        )

    def _validate_sources(
        self,
        replayed: _ReplayedInstanceRuntime,
        sources: _SourceEvidence,
    ) -> None:
        if sources.desired_snapshot.inventory_revision != len(
            sources.desired_transitions
        ):
            raise _corrupt(
                self._path,
                "Desired-state snapshot and transitions are inconsistent",
            )
        for current in replayed.instances.values():
            activation = current.activation
            try:
                selection = _desired_selection_at(
                    sources.desired_transitions,
                    revision=activation.source_inventory_revision,
                    installation_key=activation.installation_key,
                )
            except ValueError as exc:
                raise _corrupt(
                    self._path,
                    "Plugin Instance activation source revision is invalid",
                ) from exc
            if not _selection_matches_activation(selection, activation):
                raise _corrupt(
                    self._path,
                    "Plugin Instance activation is absent from desired-state history",
                )
            if current.retirement_intent is not None:
                intent = current.retirement_intent
                retirement_set = sources.retirement_sets.retirement_set(
                    intent.retirement_id
                )
                if (
                    _intent_by_id(sources).get(intent.retirement_id) != intent
                    or retirement_set is None
                    or retirement_set.intent != intent
                ):
                    raise _corrupt(
                        self._path,
                        "Plugin Instance drain contradicts retirement evidence",
                    )
            if (
                current.completion is not None
                and current.completion.completion_kind == "graceful"
            ):
                retirement_set = sources.retirement_sets.retirement_set(
                    current.completion.coordination_id
                )
                if retirement_set is None or retirement_set.state != "succeeded":
                    raise _corrupt(
                        self._path,
                        "Retired Plugin Instance lacks successful owner evidence",
                    )
        for mutable_family in replayed.families.values():
            family = mutable_family.family
            if family.lease_kind == "agent_membership":
                continue
            source_revision = family.source_inventory_revision
            if source_revision is None:
                raise _corrupt(
                    self._path,
                    "Root Plugin Instance family lacks desired-state revision",
                )
            for member in family.members:
                try:
                    selection = _desired_selection_at(
                        sources.desired_transitions,
                        revision=source_revision,
                        installation_key=member.installation_key,
                    )
                except ValueError as exc:
                    raise _corrupt(
                        self._path,
                        "Plugin Instance family source revision is invalid",
                    ) from exc
                if (
                    selection.desired_state != "installed_enabled"
                    or selection.instance_revision_ref != member.instance_revision_ref
                    or selection.package_revision != member.package_revision
                ):
                    raise _corrupt(
                        self._path,
                        "Plugin Instance family is absent from desired-state history",
                    )

    def _load_and_replay_unlocked(self) -> _ReplayedInstanceRuntime:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, PluginInstanceRuntimeEventV1] = load_jsonl(
                self._path,
                record_codec=PLUGIN_INSTANCE_RUNTIME_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_instance_runtime_record",
                    "unsupported_plugin_instance_runtime_record_version",
                }
                else "plugin_instance_runtime_journal_corrupt"
            )
            raise PluginInstanceRuntimeError(
                "Plugin Instance runtime journal cannot be decoded",
                code=code,
                path=self._path,
            ) from exc
        return _replay(snapshot.records, path=self._path)

    def _append_and_apply_unlocked(
        self,
        replayed: _ReplayedInstanceRuntime,
        event: PluginInstanceRuntimeEventV1,
    ) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_INSTANCE_RUNTIME_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )
        _apply_event(replayed, event, path=self._path)


def _empty_replay() -> _ReplayedInstanceRuntime:
    return _ReplayedInstanceRuntime(
        events=[],
        instances={},
        families={},
        operation_events={},
        idempotency_events={},
        activation_ids={},
        revocation_ids={},
        completion_ids={},
    )


def _replay(
    events: tuple[PluginInstanceRuntimeEventV1, ...],
    *,
    path: Path,
) -> _ReplayedInstanceRuntime:
    replayed = _empty_replay()
    for event in events:
        _apply_event(replayed, event, path=path)
    return replayed


def _apply_event(
    replayed: _ReplayedInstanceRuntime,
    event: PluginInstanceRuntimeEventV1,
    *,
    path: Path,
) -> None:
    if event.journal_revision != len(replayed.events) + 1:
        raise _corrupt(path, "Plugin Instance runtime revision is not contiguous")
    operation_identity = _event_operation_identity(event)
    if operation_identity is not None:
        operation_id, idempotency_key = operation_identity
        if operation_id in replayed.operation_events:
            raise _corrupt(path, "Plugin Instance operation id is duplicated")
        if idempotency_key in replayed.idempotency_events:
            raise _corrupt(path, "Plugin Instance idempotency key is duplicated")

    if event.event_kind == "activated":
        activation = event.activation
        if activation is None:
            raise _corrupt(path, "Plugin Instance activation payload is missing")
        instance_ref = activation.instance_revision_ref
        direct_family = activation.direct_host_family
        if instance_ref in replayed.instances:
            raise _corrupt(path, "Plugin Instance Revision was activated twice")
        if activation.activation_id in replayed.activation_ids:
            raise _corrupt(path, "Plugin Instance activation id is duplicated")
        if direct_family.family_id in replayed.families:
            raise _corrupt(path, "Plugin Instance lease family id is duplicated")
        if any(
            current.activation.installation_key == activation.installation_key
            and current.state == "ACTIVE"
            for current in replayed.instances.values()
        ):
            raise _corrupt(path, "Plugin Installation has two ACTIVE revisions")
        replayed.instances[instance_ref] = _MutableInstance(
            activation=activation,
            state="ACTIVE",
            retirement_intent=None,
            revocation=None,
            completion=None,
            open_family_ids={direct_family.family_id},
        )
        replayed.families[direct_family.family_id] = _MutableFamily(
            family=direct_family,
            release=None,
        )
        replayed.activation_ids[activation.activation_id] = activation
    elif event.event_kind == "family_acquired":
        acquired_family = event.family
        if acquired_family is None:
            raise _corrupt(path, "Plugin Instance family payload is missing")
        if acquired_family.lease_kind == "direct_host":
            raise _corrupt(path, "Direct-host family exists outside activation")
        if acquired_family.family_id in replayed.families:
            raise _corrupt(path, "Plugin Instance lease family id is duplicated")
        if acquired_family.lease_kind == "agent_membership":
            parent_id = acquired_family.parent_family_id
            parent = None if parent_id is None else replayed.families.get(parent_id)
            if (
                parent is None
                or parent.release is not None
                or parent.family.lease_kind
                not in {"session_membership", "agent_membership"}
                or _family_subjects(parent.family) != _family_subjects(acquired_family)
            ):
                raise _corrupt(path, "Agent membership parent is invalid")
            allowed_states = {"ACTIVE", "DRAINING"}
        else:
            allowed_states = {"ACTIVE"}
        for member in acquired_family.members:
            current = replayed.instances.get(member.instance_revision_ref)
            if (
                current is None
                or current.activation.installation_key != member.installation_key
                or current.activation.package_revision != member.package_revision
                or current.state not in allowed_states
            ):
                raise _corrupt(
                    path,
                    "Plugin Instance family member cannot be acquired",
                )
        replayed.families[acquired_family.family_id] = _MutableFamily(
            family=acquired_family,
            release=None,
        )
        for member in acquired_family.members:
            replayed.instances[member.instance_revision_ref].open_family_ids.add(
                acquired_family.family_id
            )
    elif event.event_kind == "drain_started":
        intent = event.retirement_intent
        if intent is None:
            raise _corrupt(path, "Plugin Instance drain intent is missing")
        current = replayed.instances.get(intent.instance_revision_ref)
        if (
            current is None
            or current.state != "ACTIVE"
            or current.retirement_intent is not None
        ):
            raise _corrupt(path, "Plugin Instance drain transition is invalid")
        current.state = "DRAINING"
        current.retirement_intent = intent
    elif event.event_kind == "revoke_started":
        revocation = event.revocation
        if revocation is None:
            raise _corrupt(path, "Plugin Instance revocation payload is missing")
        current = replayed.instances.get(revocation.instance_revision_ref)
        if (
            current is None
            or current.activation.installation_key != revocation.installation_key
            or current.state not in {"ACTIVE", "DRAINING"}
            or current.revocation is not None
            or revocation.revocation_id in replayed.revocation_ids
        ):
            raise _corrupt(path, "Plugin Instance revocation transition is invalid")
        current.state = "REVOKING"
        current.revocation = revocation
        replayed.revocation_ids[revocation.revocation_id] = revocation
    elif event.event_kind == "family_released":
        release = event.release
        if release is None:
            raise _corrupt(path, "Plugin Instance family release is missing")
        mutable_family = replayed.families.get(release.family_id)
        if mutable_family is None or mutable_family.release is not None:
            raise _corrupt(path, "Plugin Instance family release is invalid")
        if any(
            candidate.release is None
            and candidate.family.parent_family_id == release.family_id
            for candidate in replayed.families.values()
        ):
            raise _corrupt(path, "Plugin Instance parent released before child")
        if mutable_family.family.lease_kind == "direct_host" and any(
            replayed.instances[member.instance_revision_ref].state == "ACTIVE"
            for member in mutable_family.family.members
        ):
            raise _corrupt(path, "ACTIVE Plugin Instance released its direct host")
        mutable_family.release = release
        for member in mutable_family.family.members:
            current = replayed.instances[member.instance_revision_ref]
            if release.family_id not in current.open_family_ids:
                raise _corrupt(path, "Plugin Instance open-family index is corrupt")
            current.open_family_ids.remove(release.family_id)
    else:
        completion = event.completion
        if completion is None:
            raise _corrupt(path, "Plugin Instance completion payload is missing")
        current = replayed.instances.get(completion.instance_revision_ref)
        if (
            current is None
            or current.activation.installation_key != completion.installation_key
            or current.open_family_ids
            or current.completion is not None
            or completion.completion_id in replayed.completion_ids
        ):
            raise _corrupt(path, "Plugin Instance completion transition is invalid")
        if completion.completion_kind == "graceful":
            if (
                current.state != "DRAINING"
                or current.retirement_intent is None
                or current.retirement_intent.retirement_id != completion.coordination_id
            ):
                raise _corrupt(path, "Graceful Plugin Instance completion is invalid")
        elif (
            current.state != "REVOKING"
            or current.revocation is None
            or current.revocation.revocation_id != completion.coordination_id
        ):
            raise _corrupt(path, "Security Plugin Instance completion is invalid")
        current.state = "RETIRED"
        current.completion = completion
        replayed.completion_ids[completion.completion_id] = completion

    if operation_identity is not None:
        operation_id, idempotency_key = operation_identity
        replayed.operation_events[operation_id] = event
        replayed.idempotency_events[idempotency_key] = event
    replayed.events.append(event)


def _event_operation_identity(
    event: PluginInstanceRuntimeEventV1,
) -> tuple[str, str] | None:
    if event.activation is not None:
        return event.activation.operation_id, event.activation.idempotency_key
    if event.family is not None:
        return event.family.operation_id, event.family.idempotency_key
    if event.revocation is not None:
        return event.revocation.operation_id, event.revocation.idempotency_key
    if event.release is not None:
        return event.release.operation_id, event.release.idempotency_key
    if event.completion is not None:
        return event.completion.operation_id, event.completion.idempotency_key
    return None


def _snapshot_inventory(
    replayed: _ReplayedInstanceRuntime,
) -> PluginInstanceRuntimeInventorySnapshotV1:
    return PluginInstanceRuntimeInventorySnapshotV1(
        journal_revision=len(replayed.events),
        instances=tuple(
            sorted(
                (
                    _snapshot_instance(current)
                    for current in replayed.instances.values()
                ),
                key=_instance_snapshot_sort_key,
            )
        ),
        open_families=tuple(
            sorted(
                (
                    current.family
                    for current in replayed.families.values()
                    if current.release is None
                ),
                key=lambda item: item.family_id,
            )
        ),
    )


def _snapshot_instance(
    current: _MutableInstance,
) -> PluginInstanceRuntimeSnapshotV1:
    activation = current.activation
    return PluginInstanceRuntimeSnapshotV1(
        installation_key=activation.installation_key,
        instance_revision_ref=activation.instance_revision_ref,
        package_revision=activation.package_revision,
        activation=activation,
        state=current.state,
        retirement_intent=current.retirement_intent,
        revocation=current.revocation,
        completion=current.completion,
        open_family_ids=tuple(sorted(current.open_family_ids)),
    )


def _instance_snapshot_sort_key(
    instance: PluginInstanceRuntimeSnapshotV1,
) -> tuple[PluginInstallationKeyV1, str, int]:
    ref = instance.instance_revision_ref
    return instance.installation_key, ref.instance_id, ref.revision


def _family_subjects(
    family: PluginInstanceLeaseFamilyV1,
) -> tuple[
    tuple[
        PluginInstallationKeyV1,
        PluginInstanceRevisionRef,
        PluginPackageRevisionRefV1,
    ],
    ...,
]:
    return tuple(
        (
            member.installation_key,
            member.instance_revision_ref,
            member.package_revision,
        )
        for member in family.members
    )


def _canonical_installation_keys(
    installation_keys: tuple[PluginInstallationKeyV1, ...],
) -> tuple[PluginInstallationKeyV1, ...]:
    if not isinstance(installation_keys, tuple) or not installation_keys:
        raise ValueError("Plugin Instance acquisition requires Installations")
    if any(not isinstance(key, PluginInstallationKeyV1) for key in installation_keys):
        raise TypeError("Plugin Instance acquisition requires Installation keys")
    if len(installation_keys) != len(set(installation_keys)):
        raise ValueError("Plugin Instance acquisition Installations must be unique")
    return tuple(sorted(installation_keys))


def _desired_selection_at(
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    revision: int,
    installation_key: PluginInstallationKeyV1,
) -> PluginDesiredSelectionV1:
    if revision < 0 or revision > len(transitions):
        raise ValueError("Desired-state source revision is outside the journal")
    state = PluginInstallationStateV1.initial(installation_key)
    for transition in transitions[:revision]:
        if transition.mutation.installation_key == installation_key:
            state = transition.committed_state
    return state.selection


def _selection_matches_activation(
    selection: PluginDesiredSelectionV1,
    activation: PluginInstanceActivationV1,
) -> bool:
    return (
        selection.desired_state == "installed_enabled"
        and selection.instance_revision_ref == activation.instance_revision_ref
        and selection.package_revision == activation.package_revision
    )


def _intent_by_id(
    sources: _SourceEvidence,
) -> dict[str, PluginRetirementIntentV1]:
    return {
        intent.retirement_id: intent for intent in sources.retirement_intents.intents
    }


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _conflict(path: Path, message: str) -> PluginInstanceRuntimeError:
    return PluginInstanceRuntimeError(
        message,
        code="plugin_instance_runtime_conflict",
        path=path,
    )


def _transition_error(path: Path, message: str) -> PluginInstanceRuntimeError:
    return PluginInstanceRuntimeError(
        message,
        code="invalid_plugin_instance_runtime_transition",
        path=path,
    )


def _unavailable(path: Path, message: str) -> PluginInstanceRuntimeError:
    return PluginInstanceRuntimeError(
        message,
        code="plugin_instance_acquisition_unavailable",
        path=path,
    )


def _corrupt(path: Path, message: str) -> PluginInstanceRuntimeError:
    return PluginInstanceRuntimeError(
        message,
        code="plugin_instance_runtime_journal_corrupt",
        path=path,
    )


__all__ = [
    "PluginInstanceDesiredStateSourcePort",
    "PluginInstanceRetirementIntentSourcePort",
    "PluginInstanceRetirementSetSourcePort",
    "PluginInstanceSecurityAcceptanceSourcePort",
    "PluginInstanceRuntimeError",
    "PluginInstanceRuntimeInventorySnapshotV1",
    "PluginInstanceRuntimeLedger",
    "PluginInstanceRuntimeSnapshotV1",
    "plugin_instance_security_acceptance_journal_path",
]
