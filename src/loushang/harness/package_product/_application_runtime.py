"""Bind and recheck the authorities shared by fenced Package applications."""

from __future__ import annotations

import inspect
import json
import os
import stat
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import (
    Generic,
    Literal,
    NamedTuple,
    Protocol,
    Self,
    TypedDict,
    TypeVar,
    Unpack,
    cast,
)

from loushang.harness.conversation import ConversationHeader
from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionProjectionSourcePort,
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
    PluginManagementCommandApplication,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
    PluginManagementReadModelProjector,
    PluginSourceProjectionSourcePort,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationV1,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationProjector,
    PackageOperationExplanationV1,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._legacy_runtime import (
    FencedRuntimeOpenKwargs,
    _FencedRuntime,
    _LegacyEpoch,
    legacy_product_fence_exists,
    matches_epoch_layout,
    open_read_only_fenced_product,
)
from .product_local_wheel_runtime import (
    READ_ONLY_PRODUCT_JOURNAL_POLICY,
    PosixLocalWheelProductHostInputs,
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductRuntimeFactory,
    WindowsLocalWheelProductSessionOwner,
    _LocalWheelSelectedManifestReader,
    _repair_ordinary_posix_runtime_leases,
    _repair_ordinary_windows_runtime_leases,
    bind_read_only_local_wheel_manifests,
    bind_read_only_product_desired_state,
)
from .product_runtime import PackageProductRuntimeFactoryPort, guard_unbound_factory

_GC_RESERVATIONS_NAME = "gc-reservations.jsonl"
_GC_BINDINGS_NAME = "gc-bindings.jsonl"
_DESIRED_NAME = "desired-state.jsonl"
_MANAGEMENT_NAME = "management-operations.jsonl"
_ProductSessionOwner = (
    PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
)


def require_synchronous_admission(
    check: Callable[[], None], *, invalid_check: str, invalid_return: str
) -> None:
    if not callable(check) or inspect.iscoroutinefunction(check):
        raise TypeError(invalid_check)
    _invoke_current_admission(check, invalid_return=invalid_return)


def _invoke_current_admission(
    check: Callable[[], None], *, invalid_return: str
) -> None:
    result = cast(Callable[[], object], check)()
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError(invalid_return)


def require_current_product_admission(
    check: Callable[[], None] | None, *, label: str
) -> None:
    if check is not None:
        require_synchronous_admission(
            check,
            invalid_check=f"{label} requires a synchronous current admission check",
            invalid_return=f"{label} admission check must return None",
        )


def is_explicit_worker_plugin_id(plugin_id: object) -> bool:
    return not (
        not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id != plugin_id.strip()
    )


def select_resume_worker_candidates(
    include_candidates: bool,
    plugin_id: str | None,
    *,
    has_application_owner: bool,
    require_selected_plugin: bool = False,
    invalid: str,
) -> bool:
    """Select the Worker-capable factory only with its application owner."""
    selected = plugin_id is not None
    if (
        type(include_candidates) is not bool
        or (selected and not is_explicit_worker_plugin_id(plugin_id))
        or ((include_candidates or selected) and not has_application_owner)
        or (require_selected_plugin and not selected)
    ):
        raise ValueError(invalid)
    return include_candidates or selected


class SourceCatalogIdentity(TypedDict):
    source_root: Path
    store_id: str
    namespace_id: str
    scope_id: str


class FencedSourceCatalogRoots(NamedTuple):
    state_root: Path
    identity: SourceCatalogIdentity


def fenced_source_catalog_roots(
    runtime: _FencedRuntime,
    *,
    scope_id: str,
    no_namespace: str,
    state_root: Path | None = None,
    read_only: bool = False,
    require_existing_source: bool = False,
) -> FencedSourceCatalogRoots:
    """Bind one native fence to its Catalog and controlled Source roots."""
    switch = runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError(no_namespace)
    if require_existing_source:
        # Management ports observe a previously established Source authority.
        # A write port may prepare it only after that observation succeeds.
        if not isinstance(runtime, PackageProductPosixFencedRuntimeOwner):
            raise TypeError("Existing Product Source catalog requires a POSIX epoch")
        source_root = runtime.control_root / "product-sources"
        try:
            private_product_state_identity(
                source_root, unsafe_message="Fenced Product Source root is unsafe"
            )
        except FileNotFoundError as exc:
            raise ValueError("Fenced Product Source root is absent") from exc
        if not read_only:
            runtime.prepare_product_source_root()
        state_root = runtime.control_root / "product-state"
    elif read_only:
        if not isinstance(runtime, PackageProductPosixFencedRuntimeOwner):
            raise TypeError("Read-only Product Source catalog requires a POSIX epoch")
        runtime.require_existing_product_state_root()
        state_root = runtime.control_root / "product-state"
        source_root = runtime.control_root / "product-sources"
    else:
        if state_root is None:
            state_root = runtime.prepare_product_state_root()
        source_root = runtime.prepare_product_source_root()
    return FencedSourceCatalogRoots(
        state_root,
        SourceCatalogIdentity(
            source_root=source_root,
            store_id=runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=scope_id,
        ),
    )


@contextmanager
def fenced_source_catalog_scope(
    runtime: _FencedRuntime, *, scope_id: str, no_namespace: str
) -> Iterator[FencedSourceCatalogRoots]:
    """Hold the opened epoch while a controlled Source is pinned."""
    with closing(runtime):
        yield fenced_source_catalog_roots(
            runtime, scope_id=scope_id, no_namespace=no_namespace
        )


class FencedProductManagementState(NamedTuple):
    state_root: Path
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger
    management: PluginManagementService
    gc_bindings: PluginPackageGcBindingJournal


class _ValidateProductTopology(Protocol):
    def __call__(self, *, state_root: Path, gc_gate: PluginPackageGcReservationJournal) -> None: ...


def open_fenced_product_management_state(
    epoch: _FencedRuntime,
    *,
    validate_topology: _ValidateProductTopology,
    before_recovery: Callable[[], None] | None,
    require_current_admission: Callable[[], None] | None,
    label: str,
) -> FencedProductManagementState:
    """Establish private state and verify its topology before management replay."""
    require_current_product_admission(require_current_admission, label=label)
    if before_recovery is not None:
        before_recovery()
    state_root = epoch.prepare_product_state_root()
    require_current_product_admission(require_current_admission, label=label)
    if before_recovery is not None:
        before_recovery()
    metadata = state_root.lstat()
    epoch.assert_current()
    gate = PluginPackageGcReservationJournal(
        state_root / _GC_RESERVATIONS_NAME,
        parent_identity=(metadata.st_dev, metadata.st_ino),
    )
    require_current_product_admission(require_current_admission, label=label)
    validate_topology(state_root=state_root, gc_gate=gate)
    desired = PluginDesiredStateLedger(state_root / _DESIRED_NAME, gc_gate=gate)
    management = PluginManagementService(
        desired_state=desired, operation_journal_path=state_root / _MANAGEMENT_NAME
    )
    management.recover(
        before_replay=before_recovery,
        require_current_admission=require_current_admission,
    )
    return FencedProductManagementState(
        state_root,
        gate,
        desired,
        management,
        PluginPackageGcBindingJournal(state_root / _GC_BINDINGS_NAME),
    )


def private_product_state_identity(
    state_root: Path, *, unsafe_message: str
) -> tuple[int, int]:
    metadata = state_root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError(unsafe_message)
    return metadata.st_dev, metadata.st_ino


def open_read_only_product_management_state(
    state_root: Path,
) -> tuple[PluginDesiredStateLedger, PluginManagementService, JournalLoadPolicy]:
    """Open existing state and operation authorities with strict read policies."""

    try:
        private_product_state_identity(
            state_root, unsafe_message="Fenced Product management state is unsafe"
        )
    except FileNotFoundError as exc:
        raise ValueError("Fenced Product management state is absent") from exc
    desired = bind_read_only_product_desired_state(state_root).desired
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root / _MANAGEMENT_NAME,
        load_policy=READ_ONLY_PRODUCT_JOURNAL_POLICY,
    )
    return desired, management, READ_ONLY_PRODUCT_JOURNAL_POLICY


class PackageChangeFailureEvidence(NamedTuple):
    stage: str
    committed_revision: dict[str, object] | None
    desired_inventory_revision: int | None
    handoff_receipt_id: str | None
    handoff_evidence: str
    join_status: str


class PackageRemovalFailureEvidence(NamedTuple):
    operation_status: str
    actor_id: str | None
    pending_operation: bool
    committed_revision: int | None


class FencedProductManagementApplication(ABC):
    """Scope management and Package evidence to one POSIX Product epoch per call."""

    __slots__ = ()
    workspace_guard: Callable[[], None] | None

    @abstractmethod
    def _open_epoch(
        self, *, read_only: bool
    ) -> PackageProductPosixFencedRuntimeOwner: ...

    @abstractmethod
    def _open_write_state(
        self, runtime: PackageProductPosixFencedRuntimeOwner
    ) -> tuple[PluginDesiredStateLedger, PluginManagementService]: ...

    @abstractmethod
    def _source(
        self,
        runtime: PackageProductPosixFencedRuntimeOwner,
        desired: PluginDesiredStateLedger,
        *,
        read_only: bool,
    ) -> PluginSourceProjectionSourcePort: ...

    @abstractmethod
    def _backup_retention(
        self, runtime: PackageProductPosixFencedRuntimeOwner
    ) -> PluginBackupRetentionProjectionSourcePort: ...

    def assert_workspace_current(self) -> None:
        if self.workspace_guard is not None:
            self.workspace_guard()

    def open(
        self, *, read_only: bool
    ) -> tuple[PackageProductPosixFencedRuntimeOwner, PluginManagementApplicationPorts]:
        self.assert_workspace_current()
        runtime = self._open_epoch(read_only=read_only)
        try:
            self.assert_workspace_current()
            if read_only:
                desired, management, _ = open_read_only_product_management_state(
                    runtime.control_root / "product-state"
                )
            else:
                runtime.prepare_product_state_root()
                desired, management = self._open_write_state(runtime)
            ports = PluginManagementApplicationPorts(
                commands=PluginManagementCommandApplication(management),
                queries=PluginManagementReadModelProjector(
                    desired_state=desired,
                    operations=management,
                    retirement=management.retirement_projection,
                    source=self._source(runtime, desired, read_only=read_only),
                    backup_retention=self._backup_retention(runtime),
                ),
            )
            runtime.assert_current()
            self.assert_workspace_current()
            return runtime, ports
        except BaseException:
            runtime.close()
            raise

    @contextmanager
    def scope(
        self, *, read_only: bool
    ) -> Iterator[
        tuple[PackageProductPosixFencedRuntimeOwner, PluginManagementApplicationPorts]
    ]:
        runtime, ports = self.open(read_only=read_only)
        try:
            yield runtime, ports
            runtime.assert_current()
            self.assert_workspace_current()
        finally:
            runtime.close()

    def bind_ports(self) -> PluginManagementApplicationPorts:
        return PluginManagementApplicationPorts(
            commands=_FencedManagementCommands(self),
            queries=_FencedManagementQueries(self),
        )

    def explain_package_operation(
        self, operation_id: str
    ) -> PackageOperationExplanationV1:
        with self.scope(read_only=True) as (runtime, _):
            return PackageOperationExplanationProjector(
                PackageLifecycleJournal(
                    runtime.control_root / "product-state" / "lifecycle.jsonl"
                )
            ).explain_operation(operation_id)

    def explain_plugin_operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginOperationExplanationV1:
        with self.scope(read_only=True) as (runtime, ports):
            state_root = runtime.control_root / "product-state"
            return PluginOperationExplanationProjector(
                package_operations=PackageLifecycleJournal(
                    state_root / "lifecycle.jsonl"
                ),
                management_commands=ports.commands,
                handoffs=PackageRetentionHandoffJournal(state_root / "handoff.jsonl"),
            ).explain_operation(operation_id, correlation_id=correlation_id)

    def read_package_handoff(
        self, operation_id: str
    ) -> PackageRetentionHandoffReceiptV1 | None:
        with self.scope(read_only=True) as (runtime, _):
            return PackageRetentionHandoffJournal(
                runtime.control_root / "product-state" / "handoff.jsonl"
            ).read_operation(operation_id)

    def read_desired_transition(
        self, operation_id: str
    ) -> PluginDesiredStateJournalTransition | None:
        runtime, _ = self.open(read_only=True)
        with closing(runtime):
            return read_fenced_product_desired_transition(runtime, operation_id)

    def observe_package_change_failure(
        self, operation_id: str
    ) -> PackageChangeFailureEvidence:
        """Observe the last provable A2 stage through read-only owner calls."""
        stage = "unknown"
        committed_revision: dict[str, object] | None = None
        inventory_revision: int | None = None
        receipt_id: str | None = None
        try:
            handoff = self.read_package_handoff(operation_id)
            if handoff is not None:
                stage = handoff.state
                receipt_id = handoff.receipt_id
                desired_commit = verify_handoff_desired_commit(
                    handoff, read_transition=self.read_desired_transition
                )
                if desired_commit is not None:
                    inventory_revision, committed_revision, _ = desired_commit
                    if handoff.state == "dependency_pinned":
                        stage = "desired_committed"
        except (OSError, RuntimeError, ValueError):
            pass
        try:
            explanation = self.explain_plugin_operation(
                operation_id, correlation_id=f"cli:failed-package:{operation_id}"
            )
            handoff_evidence: str = explanation.handoff_evidence
            join_status: str = explanation.join_status
        except (OSError, RuntimeError, ValueError):
            handoff_evidence = "not_checked"
            join_status = "not_checked"
        return PackageChangeFailureEvidence(
            stage,
            committed_revision,
            inventory_revision,
            receipt_id,
            handoff_evidence,
            join_status,
        )

    def observe_package_removal_failure(
        self,
        ports: PluginManagementApplicationPorts,
        operation_id: str,
        *,
        pending_operation: bool,
    ) -> PackageRemovalFailureEvidence:
        """Observe a removal command and its Desired commit independently."""
        operation_status = "unknown"
        actor_id: str | None = None
        committed_revision: int | None = None
        try:
            observed = ports.commands.operation(
                operation_id, correlation_id=f"cli:failed-uninstall:{operation_id}"
            )
            if observed is not None and isinstance(
                observed.operation, PluginManagementOperationEventV1
            ):
                operation_status = observed.operation.status
                actor_id = observed.operation.command.mutation.actor_id
                pending_operation = operation_status != "terminal"
        except (OSError, RuntimeError, ValueError):
            pass
        try:
            transition = self.read_desired_transition(operation_id)
            if transition is not None and transition.mutation.desired_state == "absent":
                committed_revision = transition.inventory_revision
        except (OSError, RuntimeError, ValueError):
            pass
        return PackageRemovalFailureEvidence(
            operation_status, actor_id, pending_operation, committed_revision
        )


@dataclass(frozen=True, slots=True)
class _FencedManagementQueries:
    owner: FencedProductManagementApplication

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        with self.owner.scope(read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.queries.snapshot(query)


@dataclass(frozen=True, slots=True)
class _FencedManagementCommands:
    owner: FencedProductManagementApplication

    def submit(
        self, request: PluginManagementApplicationCommandV1
    ) -> PluginManagementApplicationResultV1:
        with self.owner.scope(read_only=False) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.submit(request)

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        with self.owner.scope(read_only=True) as (_, ports):
            self.owner.assert_workspace_current()
            return ports.commands.operation(operation_id, correlation_id=correlation_id)


def read_fenced_product_desired_transition(
    runtime: PackageProductPosixFencedRuntimeOwner,
    operation_id: str,
) -> PluginDesiredStateJournalTransition | None:
    """Read the exact Desired transition under the existing observation fence."""

    desired = PluginDesiredStateLedger(
        runtime.control_root / "product-state" / _DESIRED_NAME,
        load_policy=READ_ONLY_PRODUCT_JOURNAL_POLICY,
    )
    _snapshot, transitions = desired.capture_read_only()
    matches = [
        transition
        for transition in transitions
        if transition.mutation.operation_id == operation_id
    ]
    runtime.assert_current()
    if len(matches) > 1:
        raise ValueError("Desired operation identity is ambiguous")
    return matches[0] if matches else None


def verify_handoff_desired_commit(
    handoff: PackageRetentionHandoffReceiptV1,
    *,
    read_transition: Callable[[str], PluginDesiredStateJournalTransition | None],
) -> (
    tuple[int, dict[str, object], Literal["owner_receipt", "verified_transition"]]
    | None
):
    """Prove an exact Desired commit even before handoff settlement is journaled."""

    desired_request = handoff.request.desired_request
    if handoff.desired_receipt is not None:
        return (
            handoff.desired_receipt.inventory_revision,
            desired_request.root_ref.to_dict(),
            "owner_receipt",
        )
    if handoff.state != "dependency_pinned":
        return None
    transition = read_transition(desired_request.command_id)
    if transition is None:
        return None
    key = transition.mutation.installation_key
    selected = transition.committed_state.selection.package_revision
    if (
        transition.mutation.expected_inventory_revision
        != desired_request.expected_inventory_revision
        or transition.inventory_revision
        != desired_request.expected_inventory_revision + 1
        or (key.product_id, key.scope_id, key.plugin_id)
        != (
            desired_request.product_id,
            desired_request.scope_id,
            desired_request.plugin_id,
        )
        or selected is None
        or selected.plugin_version != desired_request.root_ref.version
        or selected.package_content_digest != desired_request.root_ref.artifact_digest
    ):
        return None
    return (
        transition.inventory_revision,
        desired_request.root_ref.to_dict(),
        "verified_transition",
    )


def product_management_paths_match(
    state_root: Path,
    *,
    gc_gate: PluginPackageGcReservationJournal,
    desired_state: PluginDesiredStateLedger,
    management: PluginManagementService,
    gc_bindings: PluginPackageGcBindingJournal,
) -> bool:
    return (
        gc_gate.path == state_root / _GC_RESERVATIONS_NAME
        and desired_state.path == state_root / _DESIRED_NAME
        and management.operation_journal_path == state_root / _MANAGEMENT_NAME
        and management.retirement_intent_journal_path
        == state_root / f"{_MANAGEMENT_NAME}.retirement-intents"
        and management.retirement_set_journal_path
        == state_root / f"{_MANAGEMENT_NAME}.retirement-sets"
        and gc_bindings.path == state_root / _GC_BINDINGS_NAME
    )


class _SessionOwnerFields(TypedDict):
    workspace: Path
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    runtime_version: str
    runtime_protocol_epoch: int


class _SessionEpochLayout(_LegacyEpoch, Protocol):
    def epoch_root(self, namespace_id: str) -> Path: ...


@contextmanager
def open_fenced_product_manifest_reader(
    roots: FencedRuntimeOpenKwargs,
    *,
    epoch: _SessionEpochLayout,
    scope_id: str,
    identity_prefix: str,
    product_label: str,
    workspace_guard: Callable[[], None] | None,
    read_source_policy: Callable[
        [PackageProductPosixFencedRuntimeOwner, FencedSourceCatalogRoots],
        PackageProductLocalWheelPolicy,
    ],
) -> Iterator[tuple[
    PackageProductPosixFencedRuntimeOwner,
    PackageProductLocalWheelPolicy,
    _LocalWheelSelectedManifestReader,
    PluginPackageGcReservationJournal,
]]:
    """Transfer an admitted read-only epoch with its exact selected manifests."""
    with open_read_only_fenced_product(**roots) as runtime:
        if workspace_guard is not None:
            workspace_guard()
        source_roots = fenced_source_catalog_roots(
            runtime,
            scope_id=scope_id,
            no_namespace=f"{product_label} Package Product root is not fenced",
            read_only=True,
        )
        policy = read_source_policy(runtime, source_roots)
        selected, gate = bind_read_only_local_wheel_manifests(
            runtime,
            policy=policy,
            plugin_store_root=epoch.epoch_root(source_roots.identity["namespace_id"]),
            root_store_identity=f"{identity_prefix}-root-store:{epoch.store_id}",
        )
        runtime.assert_current()
        if workspace_guard is not None:
            workspace_guard()
        yield runtime, policy, selected, gate


def bind_fenced_product_session_owner(
    epoch_runtime: _FencedRuntime,
    *,
    state_root: Path,
    scope_id: str,
    workspace_scope: Callable[[Path], str],
    resolve_epoch: Callable[[], _SessionEpochLayout],
    additional_state_paths: Iterable[tuple[Path, str]],
    compose_sources: Callable[
        [FencedSourceCatalogRoots],
        tuple[PackageProductLocalWheelPolicy, PosixLocalWheelProductHostInputs],
    ],
    identity_prefix: str,
    product_label: str,
    **fields: Unpack[_SessionOwnerFields],
) -> _ProductSessionOwner:
    """Validate one fenced workspace before publishing and binding its Sources."""
    label = f"{product_label} Product"
    package_label = f"{product_label} Package Product"
    workspace = fields["workspace"]
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError(f"{label} workspace is not canonical")
    if workspace_scope(workspace) != scope_id:
        raise ValueError(f"{label} workspace scope changed")
    runtime_version = fields["runtime_version"]
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError(f"{label} runtime version is required")
    protocol_epoch = fields["runtime_protocol_epoch"]
    if type(protocol_epoch) is not int or protocol_epoch < 1:
        raise ValueError(f"{label} runtime protocol epoch is invalid")
    epoch = resolve_epoch()
    if not matches_epoch_layout(epoch_runtime, epoch):
        raise ValueError(f"{package_label} workspace authority changed")
    current_root = epoch_runtime.prepare_product_state_root()
    if (
        state_root != current_root
        or not product_management_paths_match(
            current_root,
            gc_gate=fields["gc_gate"],
            desired_state=fields["desired_state"],
            management=fields["management"],
            gc_bindings=fields["gc_bindings"],
        )
        or any(path != current_root / name for path, name in additional_state_paths)
    ):
        raise ValueError(f"{package_label} state authority changed")
    roots = fenced_source_catalog_roots(
        epoch_runtime,
        scope_id=scope_id,
        no_namespace=f"{package_label} root is not fenced",
        state_root=current_root,
    )
    policy, host_inputs = compose_sources(roots)
    root_store_identity = f"{identity_prefix}-root-store:{epoch.store_id}"
    dependency_store_identity = f"{identity_prefix}-dependency-store:{epoch.store_id}"
    recovery_identity = f"{identity_prefix}-recovery:{epoch.store_id}"
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        return WindowsLocalWheelProductSessionOwner(
            epoch_runtime=epoch_runtime,
            host_inputs=host_inputs,
            policy=policy,
            root_store_identity=root_store_identity,
            dependency_store_identity=dependency_store_identity,
            recovery_identity=recovery_identity,
            **fields,
        )
    return PosixLocalWheelProductSessionOwner(
        epoch_runtime=epoch_runtime,
        state_root=state_root,
        plugin_store_root=epoch.epoch_root(roots.identity["namespace_id"]),
        policy=policy,
        environment=host_inputs.environment,
        acquisition_budgets=host_inputs.acquisition_budgets,
        inspection_budgets=host_inputs.inspection_budgets,
        closure_budgets=host_inputs.closure_budgets,
        root_store_identity=root_store_identity,
        dependency_store_identity=dependency_store_identity,
        recovery_identity=recovery_identity,
        **fields,
    )


def fingerprint_product_resume_epoch(
    workspace: Path,
    *,
    runtime: _FencedRuntime | None,
    legacy_roots: tuple[Path, Path, Path] | None,
    domain: bytes,
    label: str,
) -> str:
    """Observe storage identity without selecting or preparing a Product."""
    fence = None
    document: dict[str, object]
    if runtime is None:
        if legacy_roots is None:
            raise RuntimeError(f"{label} epoch is unavailable")
        control_root, state_root, package_root = legacy_roots
        if legacy_product_fence_exists(control_root):
            raise RuntimeError(f"{label} storage epoch changed")
        identity = workspace.stat()
        document = {
            "workspace": str(workspace),
            "workspaceIdentity": [identity.st_dev, identity.st_ino],
            "storage": "legacy",
            "stateRoot": str(state_root),
            "packageRoot": str(package_root),
        }
    else:
        fence = runtime.observe_current_epoch_fence()
        document = {"workspace": str(workspace), "fence": fence.to_dict()}
    encoded = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(encoded) > 8192:
        raise ValueError(f"{label} epoch dependency exceeds its byte budget")
    if runtime is not None and runtime.observe_current_epoch_fence() != fence:
        raise RuntimeError(f"{label} epoch changed")
    return sha256(domain + encoded).hexdigest()


def require_product_owner_for_factory(
    factory: PosixLocalWheelProductRuntimeFactory
    | WindowsLocalWheelProductRuntimeFactory,
    applications: Iterable[tuple[_ProductSessionOwner, _FencedRuntime]],
    *,
    owner_changed: str,
) -> _ProductSessionOwner:
    matching: list[_ProductSessionOwner] = []
    for product, runtime in applications:
        if isinstance(factory, PosixLocalWheelProductRuntimeFactory):
            if (
                not isinstance(product, PosixLocalWheelProductSessionOwner)
                or factory.state_root != product.state_root
            ):
                continue
        elif (
            not isinstance(product, WindowsLocalWheelProductSessionOwner)
            or factory.epoch_runtime is not product.epoch_runtime
            or factory.policy is not product.policy
            or factory.expected_cwd != product.workspace
        ):
            continue
        if (
            factory.management is product.management
            and factory.desired_state is product.desired_state
            and factory.gc_bindings is product.gc_bindings
            and factory.gc_gate is product.gc_gate
            and factory.runtime_lease.registry is runtime.registry
        ):
            matching.append(product)
    if len(matching) != 1:
        raise RuntimeError(owner_changed)
    factory.assert_workspace_current()
    matching[0].assert_root_gc_authority_current()
    return matching[0]


class _FencedProductApplication(Protocol):
    @property
    def epoch_runtime(self) -> _FencedRuntime: ...

    def close(self) -> None: ...


class _ProductSessionIdentity(Protocol):
    def get_header(self) -> ConversationHeader: ...
    def get_cwd(self) -> str: ...


_SessionManagerT = TypeVar("_SessionManagerT", bound=_ProductSessionIdentity)
_ProductSessionFactory = (
    PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory
)
_OwnedFactoryT = TypeVar("_OwnedFactoryT", bound=PackageProductRuntimeFactoryPort)


class OrdinaryProductSessionOwner(Generic[_SessionManagerT]):
    """Issue one ordinary Session factory from an original fenced Product."""

    __slots__ = ()
    product_owner: _ProductSessionOwner
    _product_id: str
    _label: str
    _runtime_id_prefix: str
    _session_manager_type: type[_ProductSessionIdentity]

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.product_owner,
                (PosixLocalWheelProductSessionOwner, WindowsLocalWheelProductSessionOwner),
            )
            or self.product_owner.policy.product_id != self._product_id
        ):
            raise ValueError(f"{self._label} Package Product owner is required")

    def factory_for_session(self, manager: _SessionManagerT) -> _ProductSessionFactory:
        if not isinstance(manager, self._session_manager_type):
            raise TypeError(f"{self._label} Product Session manager is required")
        session_id = manager.get_header().conversation_id
        return self.product_owner.factory_for_session(
            session_id=session_id,
            cwd=self._session_workspace(manager),
            runtime_id=self._runtime_id_prefix + sha256(session_id.encode()).hexdigest(),
        )


    def _session_workspace(self, manager: _SessionManagerT) -> Path:
        return Path(manager.get_cwd())


class FencedOrdinaryProductApplication(Generic[_SessionManagerT]):
    """Keep the original epoch through factory creation and ordinary recovery."""

    __slots__ = ()
    epoch_runtime: _FencedRuntime
    runtime_owner: OrdinaryProductSessionOwner[_SessionManagerT]
    _label: str
    _runtime_id_prefix: str

    def __post_init__(self) -> None:
        if self.runtime_owner.product_owner.epoch_runtime is not self.epoch_runtime:
            raise ValueError(f"{self._label} Product application epoch owner changed")

    def factory_for_session(self, manager: _SessionManagerT) -> _ProductSessionFactory:
        try:
            return self.runtime_owner.factory_for_session(manager)
        except PackageEpochRuntimeLeaseRegistryError as error:
            if error.code != "package_epoch_lease_orphaned":
                raise
            repair_ordinary_product_runtime_leases(
                self.runtime_owner.product_owner,
                self.epoch_runtime,
                runtime_id_prefix=self._runtime_id_prefix,
                error_prefix=self._label,
            )
            return self.runtime_owner.factory_for_session(manager)

    def close(self) -> None:
        self.epoch_runtime.close()

    def selected_source_catalog_roots(self, scope_id: str) -> FencedSourceCatalogRoots | None:
        """Observe the selected Product's roots without preparing them again."""
        product = self.runtime_owner.product_owner
        switch = self.epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            return None
        return FencedSourceCatalogRoots(
            product.state_root,
            SourceCatalogIdentity(
                source_root=product.policy.source_root,
                store_id=self.epoch_runtime.registry.store_id,
                namespace_id=switch.namespace_id,
                scope_id=scope_id,
            ),
        )


def repair_ordinary_product_runtime_leases(
    product: _ProductSessionOwner,
    epoch_runtime: _FencedRuntime,
    *,
    runtime_id_prefix: str,
    error_prefix: str,
) -> None:
    if isinstance(product, WindowsLocalWheelProductSessionOwner):
        _repair_ordinary_windows_runtime_leases(
            product, epoch_runtime, runtime_id_prefix=runtime_id_prefix, error_prefix=error_prefix
        )
    elif isinstance(product, PosixLocalWheelProductSessionOwner):
        _repair_ordinary_posix_runtime_leases(
            product, epoch_runtime, runtime_id_prefix=runtime_id_prefix, error_prefix=error_prefix
        )
    else:
        raise RuntimeError(f"{error_prefix} ordinary orphan recovery requires POSIX Product")


_ApplicationT = TypeVar("_ApplicationT", bound=_FencedProductApplication)
_FencedRuntimeT = TypeVar("_FencedRuntimeT", bound=_FencedRuntime)
_ReceiptT = TypeVar("_ReceiptT")
_SettingsT = TypeVar("_SettingsT")


class _Closeable(Protocol):
    def close(self) -> None: ...


@contextmanager
def handoff_product_open(owner: _Closeable, *, cleanup_note: str) -> Iterator[None]:
    """Transfer the original owner only when its admission or assembly succeeds."""
    try:
        yield
    except BaseException as error:
        try:
            owner.close()
        except BaseException:
            error.add_note(cleanup_note)
        raise


@contextmanager
def hold_accepted_product_adoption(
    *,
    open_epoch: Callable[[], _FencedRuntimeT],
    accept_review: Callable[[_FencedRuntimeT], _ReceiptT],
    open_application: Callable[[], _ApplicationT],
) -> Iterator[tuple[_ReceiptT, _ApplicationT]]:
    """Commit approval and release its epoch before opening the adoption owner."""
    with closing(open_epoch()) as epoch:
        receipt = accept_review(epoch)
    with closing(open_application()) as application:
        yield receipt, application


def close_product_applications(
    owners: dict[Path, _ApplicationT], retained: list[_ApplicationT]
) -> None:
    """Close every owner and retain failed releases for another close attempt."""
    failures: list[BaseException] = []
    for workspace, owner in tuple(owners.items()):
        try:
            owner.close()
        except BaseException as error:
            failures.append(error)
        else:
            del owners[workspace]
    for owner in tuple(retained):
        try:
            owner.close()
        except BaseException as error:
            failures.append(error)
        else:
            retained.remove(owner)
    if failures:
        raise failures[0]


class LegacyProductWorkspace(NamedTuple):
    control_root: Path
    state_root: Path
    package_root: Path


class FencedProductApplicationSelection(Generic[_SessionManagerT, _SettingsT], ABC):
    """Own workspace selection, Resume observation and retained epoch lifetimes."""

    _application_label: str
    _resume_epoch_domain: bytes
    _session_manager_type: type[_SessionManagerT]

    def __init__(self, *, worker_candidates: bool) -> None:
        self._worker_candidates = worker_candidates
        self._owners: dict[Path, FencedOrdinaryProductApplication[_SessionManagerT]] = {}
        self._legacy_workspaces: dict[Path, LegacyProductWorkspace] = {}
        self._retained_owners: list[FencedOrdinaryProductApplication[_SessionManagerT]] = []
        self._lock = RLock()
        self._selection_in_progress = False
        self._fenced = False

    @abstractmethod
    def _open_workspace_selection(
        self,
        workspace: Path,
        owner: FencedOrdinaryProductApplication[_SessionManagerT] | None,
        *,
        settings_manager: _SettingsT | None,
        require_current_admission: Callable[[], None] | None,
        historical_origin: Path | None = None,
    ) -> FencedOrdinaryProductApplication[_SessionManagerT] | LegacyProductWorkspace:
        """Apply Product compatibility and opening policy under the selection lock."""
        raise NotImplementedError

    def _prepare_workspace_storage(
        self,
        legacy: LegacyProductWorkspace,
        *,
        store_id: str,
        native_blocked: bool,
        require_current_admission: Callable[[], None] | None,
        needs_legacy: Callable[[], bool],
        bootstrap: Callable[[bool], None],
    ) -> LegacyProductWorkspace | None:
        """Select legacy or bootstrap a fenced workspace under the selection lock."""
        label = self._application_label
        if not legacy_product_fence_exists(legacy.control_root):
            if native_blocked or needs_legacy():
                require_current_product_admission(
                    require_current_admission, label=f"{label} Product"
                )
                return legacy
            bootstrap(True)
            return None
        if native_blocked:
            # Even a closed platform route must detect a corrupt existing fence.
            PackageEpochFenceJournal(
                legacy.control_root / "epoch.jsonl", read_only=True
            ).current(store_id)
            raise RuntimeError(f"{label} native B Session route is not yet admitted")
        bootstrap(False)
        return None

    def _select_workspace(
        self,
        workspace: Path,
        *,
        settings_manager: _SettingsT | None,
        require_current_admission: Callable[[], None] | None,
        historical_origin: Path | None = None,
    ) -> FencedOrdinaryProductApplication[_SessionManagerT] | None:
        self._require_open()
        previous = self._owners.get(workspace)
        selected = self._open_workspace_selection(
            workspace,
            previous,
            settings_manager=settings_manager,
            require_current_admission=require_current_admission,
            historical_origin=historical_origin,
        )
        if isinstance(selected, LegacyProductWorkspace):
            self._legacy_workspaces[workspace] = selected
            return None
        if selected is previous:
            return selected
        if previous is not None:
            self._retained_owners.append(previous)
        else:
            self._legacy_workspaces.pop(workspace, None)
        self._owners[workspace] = selected
        return selected

    def factory_for_session(
        self, manager: _SessionManagerT, *, settings_manager: _SettingsT | None = None
    ) -> _ProductSessionFactory | None:
        """Select workspace storage and issue the Session factory under one lock."""
        if not isinstance(manager, self._session_manager_type):
            raise TypeError(
                f"{self._application_label} Product Session manager is required"
            )
        # A legacy Session may name a workspace that has yet to be created.
        workspace = self._session_workspace(manager).resolve(strict=False)
        with self._workspace_selection_scope():
            owner = self._select_workspace(
                workspace,
                settings_manager=settings_manager,
                require_current_admission=None,
                historical_origin=self._historical_workspace(manager),
            )
            return owner.factory_for_session(manager) if owner is not None else None

    def transfer_factory_for_session(
        self,
        manager: _SessionManagerT,
        *,
        read_settings: Callable[[], _SettingsT | None],
        own_factory: Callable[[_ProductSessionFactory, Self], _OwnedFactoryT],
    ) -> _OwnedFactoryT | None:
        """Transfer this one-Session selection alongside its native factory."""

        with handoff_product_open(
            self, cleanup_note=f"{self._application_label} Product owner cleanup also failed"
        ):
            factory = self.factory_for_session(manager, settings_manager=read_settings())
            if factory is not None:
                with guard_unbound_factory(factory):
                    return own_factory(factory, self)
        self.close()
        return None

    def borrow_factory_for_session(
        self,
        manager: _SessionManagerT,
        *,
        settings_manager: _SettingsT | None,
        worker_factory: Callable[[_ProductSessionFactory, Self], PackageProductRuntimeFactoryPort]
        | None = None,
    ) -> PackageProductRuntimeFactoryPort | None:
        """Borrow a factory lease while the application retains its selection."""

        factory = self.factory_for_session(manager, settings_manager=settings_manager)
        if worker_factory is None:
            return factory
        with guard_unbound_factory(factory):
            if not isinstance(
                factory,
                (PosixLocalWheelProductRuntimeFactory, WindowsLocalWheelProductRuntimeFactory),
            ):
                raise TypeError(f"{self._application_label} Worker requires Product selection")
            return worker_factory(factory, self)

    def _session_workspace(self, manager: _SessionManagerT) -> Path:
        return Path(manager.get_cwd())

    def _historical_workspace(self, manager: _SessionManagerT) -> Path | None:
        return None

    def prepare_resume_epoch(
        self,
        workspace: Path,
        *,
        require_current_admission: Callable[[], None],
        settings_manager: _SettingsT | None = None,
        historical_origin: Path | None = None,
    ) -> str:
        """Select and recheck original storage before creating any Session lease."""
        label = self._application_label
        _require_canonical_resume_workspace(
            workspace, message=f"{label} Resume requires a canonical absolute workspace"
        )
        invalid_check = f"{label} Resume requires a synchronous current owner check"
        if not callable(require_current_admission) or inspect.iscoroutinefunction(
            require_current_admission
        ):
            raise TypeError(invalid_check)

        def current() -> None:
            _invoke_current_admission(
                require_current_admission,
                invalid_return=f"{label} Resume owner check must return None",
            )
            self._require_open()

        with self._workspace_selection_scope():
            current()
            self._select_workspace(
                workspace,
                settings_manager=settings_manager,
                require_current_admission=current,
                historical_origin=historical_origin,
            )
            current()
            return self.resume_epoch_fingerprint(workspace)

    @contextmanager
    def _hold_selected_worker_product(
        self, workspace: Path
    ) -> Iterator[_ProductSessionOwner]:
        """Recheck the selected Product while deriving a Worker Resume obligation."""
        label = self._application_label
        _require_canonical_resume_workspace(
            workspace, message=f"{label} Resume epoch workspace must be canonical"
        )
        with self._lock:
            owner = self._owners.get(workspace)
            if self._fenced or owner is None or not self._worker_candidates:
                raise RuntimeError(f"{label} Worker Product selection is unavailable")
            product = owner.runtime_owner.product_owner
            product.assert_root_gc_authority_current()
            yield product

    def product_owner_for_factory(
        self, factory: _ProductSessionFactory
    ) -> _ProductSessionOwner:
        """Recover only the Product owner that issued this exact Session factory."""
        label = self._application_label
        if not isinstance(
            factory,
            (PosixLocalWheelProductRuntimeFactory, WindowsLocalWheelProductRuntimeFactory),
        ):
            raise TypeError(f"{label} Worker requires a Product Session factory")
        with self._lock:
            if self._fenced or not self._worker_candidates:
                raise RuntimeError(f"{label} Worker Product selection is unavailable")
            return require_product_owner_for_factory(
                factory,
                (
                    (owner.runtime_owner.product_owner, owner.epoch_runtime)
                    for owner in (*self._owners.values(), *self._retained_owners)
                ),
                owner_changed=f"{label} Worker Product Session owner changed",
            )

    def resume_epoch_fingerprint(self, workspace: Path) -> str:
        """Observe the selected storage without opening or repairing a Product."""
        label = f"{self._application_label} Resume"
        _require_canonical_resume_workspace(
            workspace, message=f"{label} epoch workspace must be canonical"
        )
        with self._lock:
            owner = self._owners.get(workspace)
            if self._fenced:
                raise RuntimeError(f"{label} epoch is unavailable")
            return fingerprint_product_resume_epoch(
                workspace,
                runtime=None if owner is None else owner.epoch_runtime,
                legacy_roots=self._legacy_workspaces.get(workspace)
                if owner is None
                else None,
                domain=self._resume_epoch_domain,
                label=label,
            )

    def fence(self) -> None:
        with self._lock:
            self._fenced = True

    def close(self) -> None:
        with self._lock:
            self._reject_nested_selection()
            self._fenced = True
            self._legacy_workspaces.clear()
            close_product_applications(self._owners, self._retained_owners)

    @contextmanager
    def _workspace_selection_scope(self) -> Iterator[None]:
        # An admission check can observe the owner without nesting selection.
        with self._lock:
            self._reject_nested_selection()
            self._require_open()
            self._selection_in_progress = True
            try:
                yield
            finally:
                self._selection_in_progress = False

    def _reject_nested_selection(self) -> None:
        if self._selection_in_progress:
            raise RuntimeError(
                f"{self._application_label} Product workspace selection is in progress"
            )

    def _require_open(self) -> None:
        if self._fenced:
            raise RuntimeError(
                f"{self._application_label} Product application is closing"
            )


def _require_canonical_resume_workspace(workspace: Path, *, message: str) -> None:
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError(message)
