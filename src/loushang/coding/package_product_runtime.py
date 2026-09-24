"""Coding Session selection over an already fenced Package Product."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from threading import Lock

from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_builtin_wheel import (
    coding_base_product_local_wheel_policy,
    coding_builtin_product_local_wheel_policy,
    prepare_posix_coding_base_product_wheel,
    prepare_posix_coding_capability_product_wheels,
)
from .package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from .session_manager import SessionManager

CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH = 2


@dataclass(frozen=True, slots=True)
class CodingPackageProductStateOwners:
    """Fresh B-only management journals, separate from pre-B replay state."""

    state_root: Path
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger
    management: PluginManagementService
    gc_bindings: PluginPackageGcBindingJournal


def open_coding_package_product_state(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> CodingPackageProductStateOwners:
    """Open durable Product owners only for this workspace's fenced Store."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Coding Package Product epoch owner is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    gate = PluginPackageGcReservationJournal(state_root / "gc-reservations.jsonl")
    desired = PluginDesiredStateLedger(state_root / "desired-state.jsonl", gc_gate=gate)
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root / "management-operations.jsonl",
    )
    management.recover()
    bindings = PluginPackageGcBindingJournal(state_root / "gc-bindings.jsonl")
    epoch_runtime.assert_current()
    return CodingPackageProductStateOwners(
        state_root=state_root,
        gc_gate=gate,
        desired_state=desired,
        management=management,
        gc_bindings=bindings,
    )


@dataclass(frozen=True, slots=True)
class CodingPosixLocalWheelProductRuntimeOwner:
    """Select the exact Coding Session for a fenced Product owner."""

    product_owner: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_owner, PosixLocalWheelProductSessionOwner)
            or self.product_owner.policy.product_id != "coding"
        ):
            raise ValueError("Coding Package Product owner is required")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory:
        """Bind a live Session to one runtime lease without a legacy route."""

        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        session_id = manager.get_header().conversation_id
        return self.product_owner.factory_for_session(
            session_id=session_id,
            cwd=Path(manager.get_cwd()),
            runtime_id="coding-session:" + sha256(session_id.encode()).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CodingFencedProductApplicationOwner:
    """Retain one B epoch owner for the lifetime of a Coding application."""

    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    runtime_owner: CodingPosixLocalWheelProductRuntimeOwner

    def __post_init__(self) -> None:
        if self.runtime_owner.product_owner.epoch_runtime is not self.epoch_runtime:
            raise ValueError("Coding Product application epoch owner changed")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory:
        return self.runtime_owner.factory_for_session(manager)

    def close(self) -> None:
        self.epoch_runtime.close()


class CodingFencedProductApplicationSelection:
    """Select one B owner per workspace and retain it through application close."""

    def __init__(self) -> None:
        self._owners: dict[Path, CodingFencedProductApplicationOwner] = {}
        self._lock = Lock()
        self._fenced = False

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory | None:
        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        # The legacy Session API permits a not-yet-created cwd. Use the same
        # canonical workspace identity as its lifecycle layout; a present B
        # fence still requires the Product owner to validate the real root.
        workspace = Path(manager.get_cwd()).resolve(strict=False)
        with self._lock:
            if self._fenced:
                raise RuntimeError("Coding Product application is closing")
            owner = self._owners.get(workspace)
            if owner is None:
                lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
                epoch = resolve_coding_package_epoch_layout(lifecycle)
                try:
                    (epoch.control_root / "epoch.jsonl").lstat()
                except FileNotFoundError:
                    # A concurrent B cutover is still fenced by the old
                    # process registration before legacy Plugin preparation.
                    return None
                owner = open_coding_fenced_product_application_owner(
                    lifecycle,
                    workspace=workspace,
                    runtime_version=version("loushang"),
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                )
                self._owners[workspace] = owner
            return owner.factory_for_session(manager)

    def fence(self) -> None:
        with self._lock:
            self._fenced = True

    def close(self) -> None:
        with self._lock:
            self._fenced = True
            failures: list[BaseException] = []
            for workspace, owner in tuple(self._owners.items()):
                try:
                    owner.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    del self._owners[workspace]
            if failures:
                raise failures[0]


@dataclass(slots=True)
class CodingSessionOwnedProductRuntimeFactory:
    """Transfer a one-Session Product owner to the runtime binding's disposal."""

    factory: PosixLocalWheelProductRuntimeFactory
    selection: CodingFencedProductApplicationSelection
    _binding_issued: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    def create(
        self, request: PackageProductRuntimeRequestV1
    ) -> PackageProductRuntimeBindingV1:
        with self._lock:
            if self._binding_issued:
                raise ValueError("Coding Product Session factory already used")
            binding = self.factory.create(request)
            try:
                release = binding.on_dispose
                if release is None:
                    raise ValueError("Coding Product runtime release is missing")
                owned = replace(binding, on_dispose=self._dispose_binding(release))
            except BaseException as error:
                try:
                    binding.dispose_runtime()
                    self.selection.close()
                except BaseException:
                    error.add_note("Coding Product Session owner cleanup also failed")
                raise
            self._binding_issued = True
            return owned

    def dispose_unbound_runtime(self) -> None:
        with self._lock:
            if self._binding_issued:
                return
            self.factory.dispose_unbound_runtime()
            self.selection.close()

    def _dispose_binding(self, release: Callable[[], None]) -> Callable[[], None]:
        def dispose() -> None:
            release()
            self.selection.close()

        return dispose


def open_coding_fenced_product_application_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingFencedProductApplicationOwner:
    """Reopen the exact B fence and bind all first-party Coding Packages."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        state = open_coding_package_product_state(lifecycle, epoch_runtime)
        runtime_owner = open_coding_builtin_product_runtime_owner(
            lifecycle,
            epoch_runtime,
            state,
            workspace=workspace,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
        return CodingFencedProductApplicationOwner(epoch_runtime, runtime_owner)
    except BaseException as error:
        try:
            epoch_runtime.close()
        except BaseException:
            error.add_note("Coding Product epoch cleanup also failed")
        raise


def bootstrap_coding_builtin_product_plugins(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> bool:
    """Install and enable unseen first-party Plugins through the fenced Product.

    Only a disabled selection committed by this exact bootstrap installation
    may finish an interrupted enable. A later operator disable or remove is
    never converted back into a default install.
    """

    require_fresh_coding_product_inputs(lifecycle, settings_manager)
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        changed = False
        for plugin_id in (
            "coding.base",
            "coding.lsp.default",
            "coding.arch.default",
        ):
            changed = _bootstrap_coding_builtin_plugin(owner, plugin_id) or changed
        return changed
    finally:
        owner.close()


def require_fresh_coding_product_inputs(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
) -> None:
    """Refuse to treat legacy settings or state as a fresh Product default."""

    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding settings manager is required")
    settings = settings_manager.get_settings()
    if (
        settings.disabled_plugins
        or settings.plugin_sources
        or settings.package_roots
        or settings.package_sources
    ):
        raise RuntimeError("Coding legacy Plugin settings require explicit migration")
    state = resolve_coding_lifecycle_pre_b_members(lifecycle)
    package = resolve_coding_package_pre_b_store_members(lifecycle)
    if any(state.domain_members().values()) or any(package.domain_members().values()):
        raise RuntimeError("Coding pre-B Plugin state requires explicit adoption")


def _bootstrap_coding_builtin_plugin(
    owner: CodingFencedProductApplicationOwner, plugin_id: str
) -> bool:
    product = owner.runtime_owner.product_owner
    desired = product.desired_state
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    operation_id = (
        "coding-builtin-bootstrap:"
        + sha256(
            f"{owner.epoch_runtime.registry.store_id}:{plugin_id}".encode()
        ).hexdigest()
    )
    snapshot = desired.snapshot()
    current = snapshot.installation(key).selection.desired_state
    if current == "installed_enabled":
        return False
    if current == "absent" and any(
        item.installation_key == key for item in snapshot.installations
    ):
        raise RuntimeError("Coding builtin Product bootstrap was removed")
    bootstrap_id = f"coding-builtin-bootstrap:{secrets.token_hex(16)}"
    factory = product.factory_for_session(
        session_id=bootstrap_id,
        cwd=product.workspace,
        runtime_id=bootstrap_id,
    )
    binding: PackageProductRuntimeBindingV1 | None = None
    try:
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=bootstrap_id,
                cwd=str(product.workspace),
            )
        )
        binding.activate()
        if current == "absent":
            source = next(
                item.source_identity
                for item in product.policy.bindings
                if item.plugin_id == plugin_id
            )
            outcome = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=operation_id,
                    action="install",
                    source=source,
                    scope="project",
                ),
                entrypoint="startup",
            )
            if (
                not outcome.handled
                or outcome.record is None
                or outcome.record.lifecycle != "installed"
                or outcome.evidence.operation_id != operation_id
            ):
                raise RuntimeError("Coding builtin Product bootstrap install refused")
        expected_command_id = product.settled_install_command_id(
            operation_id=operation_id,
            plugin_id=plugin_id,
        )
        if expected_command_id is None:
            raise RuntimeError("Coding builtin Product bootstrap handoff is missing")
    finally:
        if binding is None:
            factory.dispose_unbound_runtime()
        else:
            binding.dispose_runtime()

    snapshot = desired.snapshot()
    selected = snapshot.installation(key)
    if selected.selection.desired_state != "installed_disabled":
        raise RuntimeError("Coding builtin Product bootstrap selection changed")
    prior = next(
        (
            transition
            for transition in reversed(desired.transitions())
            if transition.mutation.installation_key == key
        ),
        None,
    )
    if (
        not isinstance(prior, PluginDesiredStateTransitionV1)
        or prior.mutation.operation_id != expected_command_id
        or prior.mutation.actor_id != product.actor_id
        or prior.committed_state != selected
    ):
        raise RuntimeError("Coding builtin Product bootstrap was superseded")
    enable_id = (
        "coding-builtin-bootstrap-enable:"
        + sha256(f"{operation_id}:{snapshot.inventory_revision}".encode()).hexdigest()
    )
    enabled = product.management.submit(
        PluginManagementCommandV1(
            action="enable",
            mutation=PluginDesiredStateMutationV1(
                operation_id=enable_id,
                idempotency_key=enable_id,
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                desired_state="installed_enabled",
                package_revision=None,
                actor_id=product.actor_id,
                policy_revision=product.desired_policy_revision,
            ),
        )
    )
    if enabled.result is None or enabled.result.disposition != "succeeded":
        raise RuntimeError("Coding builtin Product bootstrap enable refused")
    return True


def open_coding_base_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    """Compose the installed base Plugin from one fenced Product authority."""

    return _open_coding_product_runtime_owner(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=False,
    )


def open_coding_builtin_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    """Compose all three first-party Packages without granting execution."""

    return _open_coding_product_runtime_owner(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=True,
    )


def _open_coding_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    include_capabilities: bool,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Coding Package Product epoch owner is required")
    if not isinstance(state, CodingPackageProductStateOwners):
        raise TypeError("Coding Package Product state owners are required")
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError("Coding Product workspace is not canonical")
    scope_id = (
        "workspace:"
        + sha256(
            b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
        ).hexdigest()
    )
    if lifecycle.scope_id != scope_id:
        raise ValueError("Coding Product workspace scope changed")
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("Coding Product runtime version is required")
    if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
        raise ValueError("Coding Product runtime protocol epoch is invalid")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    if (
        state.state_root != state_root
        or state.gc_gate.path != state_root / "gc-reservations.jsonl"
        or state.desired_state.path != state_root / "desired-state.jsonl"
        or state.management.operation_journal_path
        != state_root / "management-operations.jsonl"
        or state.management.retirement_intent_journal_path
        != state_root / "management-operations.jsonl.retirement-intents"
        or state.management.retirement_set_journal_path
        != state_root / "management-operations.jsonl.retirement-sets"
        or state.gc_bindings.path != state_root / "gc-bindings.jsonl"
    ):
        raise ValueError("Coding Package Product state authority changed")
    switch = epoch_runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError("Coding Package Product root is not fenced")
    source_root = epoch_runtime.prepare_product_source_root()
    artifact = prepare_posix_coding_base_product_wheel(source_root)
    host_inputs = PosixLocalWheelProductHostInputs.current_host(
        max_transport_bytes=2 * 1024 * 1024
    )
    policy_arguments = dict(
        project_scope_id=scope_id,
        resolution_environment_fingerprint=host_inputs.environment.fingerprint,
        policy_revision="coding-product-package-policy:1",
        quota_profile_revision="coding-product-package-quota:1",
        authority_id="coding-product-local-source",
    )
    policy = (
        coding_builtin_product_local_wheel_policy(
            artifact,
            prepare_posix_coding_capability_product_wheels(source_root),
            **policy_arguments,
        )
        if include_capabilities
        else coding_base_product_local_wheel_policy(artifact, **policy_arguments)
    )
    return CodingPosixLocalWheelProductRuntimeOwner(
        product_owner=PosixLocalWheelProductSessionOwner(
            workspace=workspace,
            state_root=state.state_root,
            plugin_store_root=epoch.epoch_root(switch.namespace_id),
            policy=policy,
            environment=host_inputs.environment,
            acquisition_budgets=host_inputs.acquisition_budgets,
            inspection_budgets=host_inputs.inspection_budgets,
            closure_budgets=host_inputs.closure_budgets,
            root_store_identity=f"coding-product-root-store:{epoch.store_id}",
            dependency_store_identity=f"coding-product-dependency-store:{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id="product:coding",
            desired_policy_revision="coding-product-desired-policy:1",
            recovery_identity=f"coding-product-recovery:{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
    )


__all__ = [
    "CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH",
    "CodingFencedProductApplicationSelection",
    "CodingFencedProductApplicationOwner",
    "CodingSessionOwnedProductRuntimeFactory",
    "CodingPackageProductStateOwners",
    "CodingPosixLocalWheelProductRuntimeOwner",
    "bootstrap_coding_builtin_product_plugins",
    "require_fresh_coding_product_inputs",
    "open_coding_fenced_product_application_owner",
    "open_coding_base_product_runtime_owner",
    "open_coding_builtin_product_runtime_owner",
    "open_coding_package_product_state",
]
