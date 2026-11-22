"""Bind and recheck the authorities shared by fenced Package applications."""

from __future__ import annotations

import inspect
import json
import os
import stat
from collections.abc import Callable, Iterable
from hashlib import sha256
from pathlib import Path
from typing import Literal, NamedTuple, Protocol, TypedDict, TypeVar, Unpack, cast

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management.assembly import bind_plugin_desired_state
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
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
_ProductSessionOwner = (
    PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
)


def require_synchronous_admission(
    check: Callable[[], None], *, invalid_check: str, invalid_return: str
) -> None:
    if not callable(check) or inspect.iscoroutinefunction(check):
        raise TypeError(invalid_check)
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


def prepare_fenced_source_catalog(
    runtime: _FencedRuntime, *, no_namespace: str
) -> tuple[str, Path, Path]:
    """Prepare both controlled Source paths after selecting the current fence."""

    switch = runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError(no_namespace)
    return (
        switch.namespace_id,
        runtime.prepare_product_state_root(),
        runtime.prepare_product_source_root(),
    )


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


def open_read_only_product_management_state(
    state_root: Path,
) -> tuple[PluginDesiredStateLedger, PluginManagementService, JournalLoadPolicy]:
    """Open existing state and operation authorities with strict read policies."""

    try:
        state_metadata = state_root.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Fenced Product management state is absent") from exc
    if (
        not stat.S_ISDIR(state_metadata.st_mode)
        or stat.S_IMODE(state_metadata.st_mode) & 0o077
        or state_metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Fenced Product management state is unsafe")
    load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)
    desired = bind_plugin_desired_state(
        state_root / _GC_RESERVATIONS_NAME,
        state_root / _DESIRED_NAME,
        load_policy=load_policy,
    ).desired
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root / _MANAGEMENT_NAME,
        load_policy=load_policy,
    )
    return desired, management, load_policy


def read_fenced_product_desired_transition(
    runtime: PackageProductPosixFencedRuntimeOwner,
    operation_id: str,
) -> PluginDesiredStateJournalTransition | None:
    """Read the exact Desired transition under the existing observation fence."""

    desired = PluginDesiredStateLedger(
        runtime.control_root / "product-state" / _DESIRED_NAME,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
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


class _CloseableApplication(Protocol):
    def close(self) -> None: ...


_ApplicationT = TypeVar("_ApplicationT", bound=_CloseableApplication)


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
