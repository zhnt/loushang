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
    TypedDict,
    TypeVar,
    Unpack,
    cast,
)

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
from loushang.harness.plugin_management.assembly import (
    PluginDesiredStateBindings,
    bind_plugin_desired_state,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationV1,
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
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
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

from ._legacy_runtime import _FencedRuntime
from .product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductRuntimeFactory,
    WindowsLocalWheelProductSessionOwner,
)

_GC_RESERVATIONS_NAME = "gc-reservations.jsonl"
_GC_BINDINGS_NAME = "gc-bindings.jsonl"
_DESIRED_NAME = "desired-state.jsonl"
_MANAGEMENT_NAME = "management-operations.jsonl"
_READ_ONLY_LOAD_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)
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


def prepare_product_state_for_recovery(
    epoch: _FencedRuntime,
    *,
    before_recovery: Callable[[], None] | None,
    require_current_admission: Callable[[], None] | None,
    label: str,
) -> tuple[Path, PluginPackageGcReservationJournal]:
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
    return state_root, gate


@contextmanager
def fenced_source_catalog_scope(
    runtime: _FencedRuntime, *, no_namespace: str
) -> Iterator[tuple[str, Path, Path]]:
    """Hold the opened epoch while a controlled Source is pinned."""

    try:
        switch = runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError(no_namespace)
        yield (
            switch.namespace_id,
            runtime.prepare_product_state_root(),
            runtime.prepare_product_source_root(),
        )
    finally:
        runtime.close()


class FencedProductManagementState(NamedTuple):
    desired_state: PluginDesiredStateLedger
    management: PluginManagementService
    gc_bindings: PluginPackageGcBindingJournal


def open_fenced_product_management_state(
    state_root: Path,
    gate: PluginPackageGcReservationJournal,
    *,
    before_recovery: Callable[[], None] | None,
    require_current_admission: Callable[[], None] | None,
) -> FencedProductManagementState:
    desired = PluginDesiredStateLedger(state_root / _DESIRED_NAME, gc_gate=gate)
    management = PluginManagementService(
        desired_state=desired, operation_journal_path=state_root / _MANAGEMENT_NAME
    )
    management.recover(
        before_replay=before_recovery,
        require_current_admission=require_current_admission,
    )
    return FencedProductManagementState(
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


def bind_read_only_product_desired_state(state_root: Path) -> PluginDesiredStateBindings:
    return bind_plugin_desired_state(
        state_root / _GC_RESERVATIONS_NAME,
        state_root / _DESIRED_NAME,
        load_policy=_READ_ONLY_LOAD_POLICY,
    )


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
        load_policy=_READ_ONLY_LOAD_POLICY,
    )
    return desired, management, _READ_ONLY_LOAD_POLICY


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
        load_policy=_READ_ONLY_LOAD_POLICY,
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
    policy: PackageProductLocalWheelPolicy
    root_store_identity: str
    dependency_store_identity: str
    management: PluginManagementService
    desired_state: PluginDesiredStateLedger
    gc_bindings: PluginPackageGcBindingJournal
    gc_gate: PluginPackageGcReservationJournal
    actor_id: str
    desired_policy_revision: str
    recovery_identity: str
    runtime_version: str
    runtime_protocol_epoch: int


def bind_fenced_product_session_owner(
    epoch_runtime: _FencedRuntime,
    *,
    state_root: Path,
    plugin_store_root: Path | None,
    host_inputs: PosixLocalWheelProductHostInputs,
    **fields: Unpack[_SessionOwnerFields],
) -> _ProductSessionOwner:
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        return WindowsLocalWheelProductSessionOwner(
            epoch_runtime=epoch_runtime, host_inputs=host_inputs, **fields
        )
    assert plugin_store_root is not None
    return PosixLocalWheelProductSessionOwner(
        epoch_runtime=epoch_runtime,
        state_root=state_root,
        plugin_store_root=plugin_store_root,
        environment=host_inputs.environment,
        acquisition_budgets=host_inputs.acquisition_budgets,
        inspection_budgets=host_inputs.inspection_budgets,
        closure_budgets=host_inputs.closure_budgets,
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
        try:
            (control_root / "epoch.jsonl").lstat()
        except FileNotFoundError:
            pass
        else:
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


_ApplicationT = TypeVar("_ApplicationT", bound=_FencedProductApplication)
_FencedRuntimeT = TypeVar("_FencedRuntimeT", bound=_FencedRuntime)
_ReceiptT = TypeVar("_ReceiptT")
_SettingsT = TypeVar("_SettingsT")


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


class FencedProductApplicationSelection(Generic[_ApplicationT, _SettingsT], ABC):
    """Own workspace selection, Resume observation and retained epoch lifetimes."""

    _application_label: str
    _resume_epoch_domain: bytes

    def __init__(self) -> None:
        self._owners: dict[Path, _ApplicationT] = {}
        self._legacy_workspaces: dict[Path, LegacyProductWorkspace] = {}
        self._retained_owners: list[_ApplicationT] = []
        self._lock = RLock()
        self._selection_in_progress = False
        self._fenced = False

    @abstractmethod
    def _open_workspace_selection(
        self,
        workspace: Path,
        owner: _ApplicationT | None,
        *,
        settings_manager: _SettingsT | None,
        require_current_admission: Callable[[], None] | None,
    ) -> _ApplicationT | LegacyProductWorkspace:
        """Apply Product compatibility and opening policy under the selection lock."""
        raise NotImplementedError

    def _select_workspace(
        self,
        workspace: Path,
        *,
        settings_manager: _SettingsT | None,
        require_current_admission: Callable[[], None] | None,
    ) -> _ApplicationT | None:
        self._require_open()
        previous = self._owners.get(workspace)
        selected = self._open_workspace_selection(
            workspace,
            previous,
            settings_manager=settings_manager,
            require_current_admission=require_current_admission,
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

    def _prepare_resume_epoch(
        self,
        workspace: Path,
        *,
        require_current_admission: Callable[[], None],
        settings_manager: _SettingsT | None = None,
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
            )
            current()
            return self.resume_epoch_fingerprint(workspace)

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
