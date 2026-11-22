"""Ledger binding and policy-bound defaults; callers retain Product admission."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, TypedDict, TypeVar

from loushang.harness.journal import JournalLoadPolicy, journal_file_lock
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationPorts,
    PluginManagementCommandApplication,
    PluginManagementReadModelProjector,
    PluginSourceProjectionSourcePort,
)
from loushang.harness.plugin_management.enablement_migration import (
    PLUGIN_ENABLEMENT_MIGRATION_EPOCH,
    PluginEnablementMigrationCoordinator,
    PluginEnablementMigrationJournal,
    plugin_enablement_legacy_input_fingerprint,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRetirementCompletionV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.package_records import PluginCleanupAttemptV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentLedger,
    PluginRetirementIntentV1,
)
from loushang.harness.plugin_management.retirement_sets import PluginRetirementSetLedger
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService

if TYPE_CHECKING:
    from loushang.harness.resources.packages.materializer import PackageMaterializer
    from loushang.harness.resources.plugins.authority import (
        PluginRuntimeResolution,
    )
    from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


@dataclass(frozen=True, slots=True)
class PluginDesiredStateBindings:
    gc_reservations: PluginPackageGcReservationJournal
    desired: PluginDesiredStateLedger


def bind_plugin_desired_state(
    gc_path: str | Path,
    desired_state_path: str | Path,
    *,
    load_policy: JournalLoadPolicy | None,
) -> PluginDesiredStateBindings:
    """Bind Desired state to the GC gate that protects its references."""

    gate = PluginPackageGcReservationJournal(gc_path, load_policy=load_policy)
    desired = PluginDesiredStateLedger(
        desired_state_path, gc_gate=gate, load_policy=load_policy
    )
    return PluginDesiredStateBindings(gate, desired)


class _LegacyManagementLayout(Protocol):
    @property
    def package_gc_reservations(self) -> Path: ...
    @property
    def desired_state(self) -> Path: ...
    @property
    def management_operations(self) -> Path: ...
    @property
    def retirement_intents(self) -> Path: ...
    @property
    def retirement_sets(self) -> Path: ...
    @property
    def enablement_migration(self) -> Path: ...
    @property
    def instance_runtime(self) -> Path: ...
    @property
    def package_lifecycle(self) -> Path: ...


class LegacyPluginLifecycleBindings(TypedDict):
    desired: PluginDesiredStateLedger
    management: PluginManagementService
    enablement_migrations: PluginEnablementMigrationCoordinator
    instances: PluginInstanceRuntimeLedger
    retirement_sets: PluginRetirementSetLedger
    packages: PluginPackageLifecycleLedger
    _gc_reservations: PluginPackageGcReservationJournal
    security: PluginInstanceSecurityRetirementJournal
    _owns_process_startup_lease: bool


_LifecycleT = TypeVar("_LifecycleT")


def assemble_legacy_plugin_management(
    layout: _LegacyManagementLayout,
    *,
    startup_id: str,
    startup: AbstractContextManager[bool],
    runtime_version: Callable[[], str],
    read_only: bool,
    source: PluginSourceProjectionSourcePort | None,
    security_acceptances: PluginInstanceSecurityRetirementJournal | None,
    build_lifecycle: Callable[[LegacyPluginLifecycleBindings], _LifecycleT] | None,
) -> PluginManagementApplicationPorts | _LifecycleT:
    """Assemble and reconcile the legacy ledgers under the existing startup scope."""

    with startup as owns_startup:
        gc_path = layout.package_gc_reservations
        desired_path = layout.desired_state
        operations_path = layout.management_operations
        intents_path = layout.retirement_intents
        sets_path = layout.retirement_sets
        migration_path = layout.enablement_migration
        load_policy = (
            JournalLoadPolicy(partial_tail="raise", create_lock=False)
            if read_only
            else None
        )
        desired_binding = bind_plugin_desired_state(
            gc_path, desired_path, load_policy=load_policy
        )
        gate, desired = desired_binding.gc_reservations, desired_binding.desired
        intents = PluginRetirementIntentLedger(intents_path, load_policy=load_policy)
        retirement_sets = PluginRetirementSetLedger(
            sets_path, retirement_intents=intents, load_policy=load_policy
        )
        management = PluginManagementService(
            desired_state=desired,
            operation_journal_path=operations_path,
            retirement_intents=intents,
            retirement_sets=retirement_sets,
            load_policy=load_policy,
        )
        migration_journal = PluginEnablementMigrationJournal(
            migration_path, load_policy=load_policy
        )
        migration_journal.assert_runtime_compatible(
            supported_migration_epoch=PLUGIN_ENABLEMENT_MIGRATION_EPOCH,
            runtime_version=runtime_version(),
        )
        if not read_only:
            management.recover()
        migrations = None
        if build_lifecycle is not None:
            migration_runtime_version = runtime_version()
            migrations = PluginEnablementMigrationCoordinator(
                journal=migration_journal,
                desired_state=desired,
                commands=PluginManagementCommandApplication(management),
                runtime_version=migration_runtime_version,
            )

        instance_path = layout.instance_runtime
        package_path = layout.package_lifecycle
        security = security_acceptances or (
            PluginInstanceSecurityRetirementJournal.for_instance_runtime(
                instance_path, load_policy=load_policy
            )
        )
        instances = PluginInstanceRuntimeLedger(
            instance_path,
            management_operation_journal_path=management.operation_journal_path,
            desired_state=desired,
            retirement_intents=intents,
            retirement_sets=retirement_sets,
            security_acceptances=security,
            gc_gate=gate,
            load_policy=load_policy,
        )
        packages = PluginPackageLifecycleLedger(
            package_path,
            startup_id=startup_id,
            desired_state=desired,
            instance_runtime=instances,
            retirement_sets=retirement_sets,
            gc_gate=gate,
            load_policy=load_policy,
        )
        if build_lifecycle is not None:
            assert migrations is not None
            return build_lifecycle(
                LegacyPluginLifecycleBindings(
                    desired=desired,
                    management=management,
                    enablement_migrations=migrations,
                    instances=instances,
                    retirement_sets=retirement_sets,
                    packages=packages,
                    _gc_reservations=gate,
                    security=security,
                    _owns_process_startup_lease=owns_startup,
                )
            )
        return PluginManagementApplicationPorts(
            commands=PluginManagementCommandApplication(management),
            queries=PluginManagementReadModelProjector(
                desired_state=desired,
                operations=management,
                migrations=migration_journal,
                source=source,
                instances=instances,
                packages=packages,
                retirement=retirement_sets,
            ),
        )


@dataclass(frozen=True, slots=True)
class _SettledHostRetirementPolicy:
    """Product assertion that this direct-host route requires no further shutdown."""

    cleanup_kind: str
    handoff_namespace: str
    cleanup_reference_namespace: str
    attempt_namespace: str
    success_result_code: str
    outcome_namespace: str
    completion_namespace: str
    completion_reference_namespace: str
    family_release: Callable[
        [PluginInstanceLeaseFamilyV1], PluginInstanceLeaseFamilyReleaseV1
    ]


def _prepare_gc_writer_epoch(
    *,
    coordination_lock: Path,
    packages: PluginPackageLifecycleLedger,
    reservations: PluginPackageGcReservationJournal,
    desired: PluginDesiredStateLedger,
    instances: PluginInstanceRuntimeLedger,
    unavailable_error: Callable[[], RuntimeError],
) -> None:
    with journal_file_lock(coordination_lock, "exclusive"):
        if (
            not packages.gc_reservation_graph_bound_to(reservations)
            or reservations.snapshot().active
        ):
            raise unavailable_error()
        packages.gc_candidates()
        desired.seal_gc_writer_epoch()
        instances.seal_gc_writer_epoch()
        packages.seal_gc_writer_epoch()


def _gc_writer_epoch_ready(
    *,
    packages: PluginPackageLifecycleLedger,
    reservations: PluginPackageGcReservationJournal,
    desired: PluginDesiredStateLedger,
    instances: PluginInstanceRuntimeLedger,
) -> bool:
    return (
        packages.gc_reservation_graph_bound_to(reservations)
        and desired.gc_writer_epoch_sealed()
        and instances.gc_writer_epoch_sealed()
        and packages.gc_writer_epoch_sealed()
    )


def _complete_settled_host_retirement(
    intent: PluginRetirementIntentV1,
    *,
    retirement_sets: PluginRetirementSetLedger,
    instances: PluginInstanceRuntimeLedger,
    packages: PluginPackageLifecycleLedger,
    scope_id: str,
    policy: _SettledHostRetirementPolicy,
) -> None:
    retirement_set = retirement_sets.snapshot().retirement_set(intent.retirement_id)
    if retirement_set is None or retirement_set.state != "succeeded":
        return
    runtime = instances.snapshot()
    instance = runtime.instance(intent.instance_revision_ref)
    if instance is None or instance.state == "RETIRED":
        return
    direct_family = instance.activation.direct_host_family
    open_family_ids = set(instance.open_family_ids)
    if open_family_ids not in ({direct_family.family_id}, set()):
        return
    identity = intent.retirement_id
    # The cleanup handoff is write-ahead: after it appends the durable task
    # it releases the direct-host family.  Therefore an empty family set is
    # a valid interrupted state, and replaying the same operation must
    # resume the task rather than wait forever for a family already handed
    # off.
    task = packages.handoff_cleanup_and_release(
        direct_family.family_id,
        retirement_target_id=None,
        cleanup_kind=policy.cleanup_kind,
        operation_id=f"{policy.handoff_namespace}:{identity}",
        idempotency_key=f"{policy.handoff_namespace}:{identity}",
        cleanup_reference=f"{policy.cleanup_reference_namespace}:{scope_id}",
        family_release=policy.family_release(direct_family),
    )
    packages.record_cleanup_attempt(
        PluginCleanupAttemptV1(
            cleanup_id=task.cleanup_id,
            operation_id=f"{policy.attempt_namespace}:{identity}",
            idempotency_key=f"{policy.attempt_namespace}:{identity}",
            attempt=1,
            disposition="succeeded",
            result_code=policy.success_result_code,
            retry_not_before_epoch_ms=None,
            outcome_reference=f"{policy.outcome_namespace}:{scope_id}",
        )
    )
    instances.complete_retirement(
        PluginInstanceRetirementCompletionV1.create(
            completion_kind="graceful",
            coordination_id=intent.retirement_id,
            installation_key=instance.installation_key,
            instance_revision_ref=instance.instance_revision_ref,
            operation_id=f"{policy.completion_namespace}:{identity}",
            idempotency_key=f"{policy.completion_namespace}:{identity}",
            completion_reference=f"{policy.completion_reference_namespace}:{scope_id}",
        )
    )


@dataclass(frozen=True, slots=True)
class _FirstPartyDefaultPolicy:
    product_id: str
    product_label: str
    actor_id: str
    policy_revision: str
    approval_reference: str
    operation_id_prefix: str
    error_code_prefix: str
    make_error: Callable[[str, str], Exception]


class _FirstPartyBootstrapScope(Protocol):
    @property
    def scope_id(self) -> str: ...


class _FirstPartyDefaultBootstrap:
    """Resume only this Product's own default install through existing commands."""

    __slots__ = ()
    layout: _FirstPartyBootstrapScope
    desired: PluginDesiredStateLedger
    management: PluginManagementService
    _first_party_default_policy: ClassVar[_FirstPartyDefaultPolicy]

    def bootstrap_first_party_default(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> None:
        """Install+enable only a truly unseen first-party Installation.

        An absent record retained after remove is deliberately *seen* and is
        therefore never resurrected by Product composition.
        """

        policy = self._first_party_default_policy
        if (
            not isinstance(key, PluginInstallationKeyV1)
            or key.product_id != policy.product_id
            or key.installation_scope != "workspace"
            or key.scope_id != self.layout.scope_id
        ):
            raise policy.make_error(
                f"First-party default Installation is outside this {policy.product_label} scope",
                f"{policy.error_code_prefix}_default_bootstrap_scope_mismatch",
            )
        if (
            not isinstance(package_revision, PluginPackageRevisionRefV1)
            or package_revision.plugin_id != key.plugin_id
        ):
            raise policy.make_error(
                "First-party default Package Revision changed Plugin identity",
                f"{policy.error_code_prefix}_default_bootstrap_revision_mismatch",
            )
        # The two management commands are individually durable.  This loop is
        # the Product transaction coordinator: it resumes only its own exact
        # default install, stops at any operator-authored state, and retries a
        # CAS race with a fresh operation identity.
        for _attempt in range(32):
            snapshot = self.desired.snapshot()
            state = snapshot.installation(key)
            seen = any(item.installation_key == key for item in snapshot.installations)
            if not seen:
                error = self._submit_default(
                    key,
                    action="install",
                    desired_state="installed_disabled",
                    package_revision=package_revision,
                    expected_inventory_revision=snapshot.inventory_revision,
                )
                if error == "plugin_inventory_revision_conflict":
                    continue
                if error is not None:
                    raise policy.make_error(
                        "First-party Plugin bootstrap install failed",
                        error,
                    )
                continue
            if state.selection.desired_state == "installed_enabled":
                return
            if not self._is_own_default_install(
                key,
                package_revision=package_revision,
            ):
                return
            error = self._submit_default(
                key,
                action="enable",
                desired_state="installed_enabled",
                package_revision=None,
                expected_inventory_revision=snapshot.inventory_revision,
            )
            if error == "plugin_inventory_revision_conflict":
                continue
            if error is not None:
                raise policy.make_error(
                    "First-party Plugin bootstrap enable failed",
                    error,
                )
            return
        raise policy.make_error(
            "First-party Plugin bootstrap could not linearize",
            f"{policy.error_code_prefix}_default_bootstrap_busy",
        )

    def _is_own_default_install(
        self,
        key: PluginInstallationKeyV1,
        *,
        package_revision: PluginPackageRevisionRefV1,
    ) -> bool:
        policy = self._first_party_default_policy
        matching = tuple(
            transition
            for transition in self.desired.transitions()
            if transition.mutation.installation_key == key
        )
        if not matching:
            return False
        mutation = matching[-1].mutation
        return (
            isinstance(mutation, PluginDesiredStateMutationV1)
            and mutation.desired_state == "installed_disabled"
            and mutation.package_revision == package_revision
            and mutation.actor_id == policy.actor_id
            and mutation.policy_revision == policy.policy_revision
            and mutation.approval_reference == policy.approval_reference
        )

    def _submit_default(
        self,
        key: PluginInstallationKeyV1,
        *,
        action: Literal["install", "enable"],
        desired_state: Literal["installed_disabled", "installed_enabled"],
        package_revision: PluginPackageRevisionRefV1 | None,
        expected_inventory_revision: int,
    ) -> str | None:
        policy = self._first_party_default_policy
        identity = hashlib.sha256(
            repr((key, action, package_revision, expected_inventory_revision)).encode(
                "utf-8"
            )
        ).hexdigest()
        event = self.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"{policy.operation_id_prefix}{identity}",
                    idempotency_key=f"{policy.operation_id_prefix}{identity}",
                    expected_inventory_revision=expected_inventory_revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=package_revision,
                    actor_id=policy.actor_id,
                    policy_revision=policy.policy_revision,
                    approval_reference=policy.approval_reference,
                ),
            )
        )
        result = getattr(event, "result", None)
        if result is None:
            return f"{policy.error_code_prefix}_default_management_failed"
        if result.disposition != "succeeded":
            return (
                result.error_code
                or f"{policy.error_code_prefix}_default_management_failed"
            )
        return None


class _ManagedPluginLease(Protocol):
    @property
    def package_revision(self) -> PluginPackageRevisionRefV1: ...
    @property
    def instance_revision_ref(self) -> PluginInstanceRevisionRef: ...
    def close(self) -> None: ...


_ManagedLeaseT = TypeVar("_ManagedLeaseT", bound=_ManagedPluginLease, covariant=True)
_AssemblyT = TypeVar("_AssemblyT")
_ConfigurationT = TypeVar("_ConfigurationT")


class _ManagedPluginLifecycle(Protocol[_ManagedLeaseT]):
    @property
    def desired(self) -> PluginDesiredStateLedger: ...
    @property
    def enablement_migrations(self) -> PluginEnablementMigrationCoordinator: ...
    def installation_key(self, plugin_id: str) -> PluginInstallationKeyV1: ...
    def migrate_legacy_enablement(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1 | None,
        *,
        legacy_disabled: bool,
        manifest_enabled_default: bool,
        legacy_input_fingerprint: str,
    ) -> object: ...
    def reconcile_retirements(self) -> None: ...
    def acquire_session(
        self,
        key: PluginInstallationKeyV1,
        *,
        session_id: str,
        lease_attempt_id: str,
        owner_contributions: tuple[tuple[str, tuple[str, ...]], ...],
        session_owner_id: str | None = None,
    ) -> _ManagedLeaseT: ...


class _ManagedPluginSpec(Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def source_root(self) -> Callable[[], Path]: ...


_SpecT = TypeVar("_SpecT", bound=_ManagedPluginSpec)


@dataclass(frozen=True, slots=True)
class _ManagedPluginErrors:
    facts: Mapping[str, tuple[str, str]]
    make_error: Callable[[str, str], Exception]
    cleanup_notes: Mapping[str, str]

    def make(self, kind: str, plugin_id: str = "") -> Exception:
        message, code = self.facts[kind]
        return self.make_error(message.format(plugin_id=plugin_id), code)


def _prepare_managed_plugin_runtime(
    *,
    lifecycle: _ManagedPluginLifecycle[_ManagedLeaseT],
    package_materializer: PackageMaterializer,
    plugin_id: str,
    session_id: str,
    session_owner_id: str | None,
    legacy_disabled: bool,
    source_root: Callable[[], Path],
    owner_contributions: Callable[[], tuple[tuple[str, tuple[str, ...]], ...]],
    finish: Callable[
        [PluginRuntimeResolution, PluginInstanceRevisionRef, _ManagedLeaseT], _AssemblyT
    ],
    errors: _ManagedPluginErrors,
    state_cleanup: Callable[[], None] | None,
) -> _AssemblyT | None:
    """Resolve and pin one exact managed runtime; Product projects its plan."""
    from loushang.harness.resources.plugins.authority import (
        PluginResolutionAuthority,
        PluginRuntimeResolution,
    )
    from loushang.harness.resources.plugins.manifest import PluginManifestError
    from loushang.harness.resources.plugins.revisions import PluginRevisionError
    from loushang.harness.resources.plugins.types import PluginSource

    key = lifecycle.installation_key(plugin_id)
    snapshot = lifecycle.desired.snapshot()
    state = snapshot.installation(key)
    seen = any((item.installation_key == key for item in snapshot.installations))
    if seen and lifecycle.enablement_migrations.journal.snapshot(key) is None:
        lifecycle.migrate_legacy_enablement(
            key,
            state.selection.package_revision,
            legacy_disabled=legacy_disabled,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key, legacy_disabled=legacy_disabled, manifest_enabled_default=True
            ),
        )
        state = lifecycle.desired.snapshot().installation(key)
    runtime: PluginRuntimeResolution | None = None
    lease: _ManagedLeaseT | None = None
    try:
        if not seen:
            authority = PluginResolutionAuthority()
            inspection = authority.inspect(PluginSource(path=source_root()))
            runtime = authority.publish_runtime(
                (inspection,), binding_store=package_materializer
            )
            [package] = runtime.packages
            [binding] = runtime.bindings
            revision = PluginPackageRevisionRefV1.from_published_package(
                package, source_identity=binding.source_identity
            )
            manifest_default = package.manifest.enabled
            lifecycle.migrate_legacy_enablement(
                key,
                revision,
                legacy_disabled=legacy_disabled,
                manifest_enabled_default=manifest_default,
                legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                    key,
                    legacy_disabled=legacy_disabled,
                    manifest_enabled_default=manifest_default,
                ),
            )
            state = lifecycle.desired.snapshot().installation(key)
        else:
            lifecycle.reconcile_retirements()
        if state.selection.desired_state != "installed_enabled":
            if runtime is not None:
                runtime.close()
            if state_cleanup is not None:
                state_cleanup()
            return None
        selected_revision = state.selection.package_revision
        selected_instance = state.selection.instance_revision_ref
        if selected_revision is None or selected_instance is None:
            raise errors.make("management_selection_incomplete")
        if runtime is None:
            try:
                replay_binding = package_materializer.get_plugin_binding_by_revision(
                    selected_revision.package_source_identity,
                    content_digest=selected_revision.package_content_digest,
                    dependency_lock_digest=selected_revision.dependency_lock_digest,
                )
            except PluginManifestError as exc:
                raise errors.make("binding_lock_replay_invalid") from exc
            if replay_binding is None:
                raise errors.make("binding_replay_unavailable")
            try:
                package = package_materializer.reopen_plugin_package(replay_binding)
            except PluginRevisionError as exc:
                error_kind = (
                    "revision_replay_unavailable"
                    if exc.code == "plugin_revision_unavailable"
                    else "revision_replay_integrity_failed"
                )
                raise errors.make(error_kind) from exc
            except PluginManifestError as exc:
                raise errors.make("binding_replay_invalid") from exc
            runtime = PluginRuntimeResolution(
                packages=(package,), plugins=(), bindings=(replay_binding,)
            )
        [package] = runtime.packages
        [binding] = runtime.bindings
        actual_revision = PluginPackageRevisionRefV1.from_published_package(
            package, source_identity=binding.source_identity
        )
        if actual_revision != selected_revision:
            raise errors.make("selected_revision_mismatch")
        lease = lifecycle.acquire_session(
            key,
            session_id=session_id,
            lease_attempt_id=secrets.token_hex(16),
            owner_contributions=owner_contributions(),
            session_owner_id=session_owner_id,
        )
        if (
            lease.package_revision != selected_revision
            or lease.instance_revision_ref != selected_instance
        ):
            raise errors.make("session_lease_mismatch")
        return finish(runtime, selected_instance, lease)
    except BaseException as error:
        if lease is not None:
            try:
                lease.close()
            except BaseException as cleanup_error:
                error.add_note(
                    errors.cleanup_notes["lease"].format(error=cleanup_error)
                )
        if runtime is not None:
            try:
                runtime.close()
            except BaseException as cleanup_error:
                error.add_note(
                    errors.cleanup_notes["revision"].format(error=cleanup_error)
                )
        if state_cleanup is not None:
            try:
                state_cleanup()
            except BaseException as cleanup_error:
                error.add_note(
                    errors.cleanup_notes["state"].format(error=cleanup_error)
                )
        raise


def _resolve_managed_plugin_runtimes(
    configurations: Mapping[str, _ConfigurationT],
    specs: Sequence[_SpecT],
    *,
    session_id: str,
    package_materializer: PackageMaterializer,
    lifecycle: _ManagedPluginLifecycle[_ManagedLeaseT] | None,
    session_owner_id: str | None,
    legacy_disabled_plugin_ids: frozenset[str],
    owner_contributions: Callable[[_SpecT], tuple[tuple[str, tuple[str, ...]], ...]],
    errors: _ManagedPluginErrors,
    attach_failure: Callable[
        [BaseException, PluginRuntimeResolution, Mapping[str, _ManagedLeaseT]], None
    ],
) -> tuple[
    PluginRuntimeResolution, Mapping[str, _ConfigurationT], Mapping[str, _ManagedLeaseT]
]:
    """Retain the exact ordered prefix and leases for the Product custodian."""
    from loushang.harness.resources.plugins.authority import (
        PluginResolutionAuthority,
        PluginRuntimeResolution,
    )
    from loushang.harness.resources.plugins.manifest import PluginManifestError
    from loushang.harness.resources.plugins.revisions import PluginRevisionError
    from loushang.harness.resources.plugins.types import PluginSource

    authority = PluginResolutionAuthority()
    if lifecycle is None:
        inspections = tuple(
            (authority.inspect(PluginSource(path=spec.source_root())) for spec in specs)
        )
        return (
            authority.publish_runtime(inspections, binding_store=package_materializer),
            dict(configurations),
            {},
        )
    packages = []
    plugins = []
    bindings = []
    selected_configurations: dict[str, _ConfigurationT] = {}
    leases: dict[str, _ManagedLeaseT] = {}
    current_package = None
    try:
        for spec in specs:
            current_package = None
            key = lifecycle.installation_key(spec.plugin_id)
            snapshot = lifecycle.desired.snapshot()
            state = snapshot.installation(key)
            seen = any(
                (item.installation_key == key for item in snapshot.installations)
            )
            legacy_disabled = spec.plugin_id in legacy_disabled_plugin_ids
            if seen and lifecycle.enablement_migrations.journal.snapshot(key) is None:
                lifecycle.migrate_legacy_enablement(
                    key,
                    state.selection.package_revision,
                    legacy_disabled=legacy_disabled,
                    manifest_enabled_default=True,
                    legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                        key,
                        legacy_disabled=legacy_disabled,
                        manifest_enabled_default=True,
                    ),
                )
                state = lifecycle.desired.snapshot().installation(key)
            package = None
            binding = None
            if not seen:
                published = authority.publish_runtime(
                    (authority.inspect(PluginSource(path=spec.source_root())),),
                    binding_store=package_materializer,
                )
                [package] = published.packages
                [binding] = published.bindings
                current_package = package
                revision = PluginPackageRevisionRefV1.from_published_package(
                    package, source_identity=binding.source_identity
                )
                manifest_default = package.manifest.enabled
                lifecycle.migrate_legacy_enablement(
                    key,
                    revision,
                    legacy_disabled=legacy_disabled,
                    manifest_enabled_default=manifest_default,
                    legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                        key,
                        legacy_disabled=legacy_disabled,
                        manifest_enabled_default=manifest_default,
                    ),
                )
                state = lifecycle.desired.snapshot().installation(key)
            lifecycle.reconcile_retirements()
            if state.selection.desired_state != "installed_enabled":
                if package is not None:
                    package.revision_handle.close()
                    current_package = None
                continue
            selected_revision = state.selection.package_revision
            selected_instance = state.selection.instance_revision_ref
            if selected_revision is None or selected_instance is None:
                raise errors.make("management_selection_incomplete", spec.plugin_id)
            if package is None or binding is None:
                try:
                    binding = package_materializer.get_plugin_binding_by_revision(
                        selected_revision.package_source_identity,
                        content_digest=selected_revision.package_content_digest,
                        dependency_lock_digest=selected_revision.dependency_lock_digest,
                    )
                except PluginManifestError as exc:
                    raise errors.make("binding_replay_invalid", spec.plugin_id) from exc
                if binding is None:
                    raise errors.make("binding_replay_unavailable", spec.plugin_id)
                try:
                    package = package_materializer.reopen_plugin_package(binding)
                    current_package = package
                except PluginRevisionError as exc:
                    raise errors.make("revision_replay_failed", spec.plugin_id) from exc
            actual_revision = PluginPackageRevisionRefV1.from_published_package(
                package, source_identity=binding.source_identity
            )
            if actual_revision != selected_revision:
                raise errors.make("selected_revision_mismatch", spec.plugin_id)
            lease = lifecycle.acquire_session(
                key,
                session_id=session_id.strip(),
                lease_attempt_id=secrets.token_hex(16),
                owner_contributions=owner_contributions(spec),
                session_owner_id=session_owner_id,
            )
            leases[spec.plugin_id] = lease
            if (
                lease.package_revision != selected_revision
                or lease.instance_revision_ref != selected_instance
            ):
                raise errors.make("session_lease_mismatch", spec.plugin_id)
            packages.append(package)
            current_package = None
            plugins.append(authority.project_package(package))
            bindings.append(binding)
            selected_configurations[spec.plugin_id] = configurations[spec.plugin_id]
        return (
            PluginRuntimeResolution(
                packages=tuple(packages),
                plugins=tuple(plugins),
                bindings=tuple(bindings),
            ),
            selected_configurations,
            leases,
        )
    except BaseException as error:
        failure_packages = list(packages)
        if current_package is not None and current_package not in failure_packages:
            failure_packages.append(current_package)
        attach_failure(
            error,
            PluginRuntimeResolution(
                packages=tuple(failure_packages),
                plugins=tuple(plugins),
                bindings=tuple(bindings),
            ),
            dict(leases),
        )
        raise
