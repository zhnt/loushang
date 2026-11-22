"""Keep private-data operations inside their existing Product fences."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.workspace.paths import assert_workspace_directory_identity

from ._application_runtime import (
    bind_read_only_product_desired_state,
    private_product_state_identity,
)

if TYPE_CHECKING:
    from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
    from loushang.harness.plugin_management.package_gc_reservation import (
        PluginPackageGcReservationJournal,
    )

    from .product_local_wheel_runtime import (
        PosixLocalWheelProductSessionOwner,
        WindowsLocalWheelProductSessionOwner,
    )


@contextmanager
def private_data_mutation_fence(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    *,
    active_message: str,
    require_write: bool,
) -> Iterator[None]:
    """Hold quiescence and the exclusive GC gate through a Product operation."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(active_message)
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=require_write):
            yield
        product.assert_root_gc_authority_current()


@contextmanager
def windows_private_data_read_fence(
    product: WindowsLocalWheelProductSessionOwner, *, label: str
) -> Iterator[None]:
    """Observe the native Product through its existing non-repairing GC gate."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(f"{label} private-data Product runtime is active")
        product.assert_private_data_read_authority_current()
        with product.gc_gate.read_guard():
            yield
        product.assert_private_data_read_authority_current()


@contextmanager
def windows_private_data_read_descriptor(
    product: WindowsLocalWheelProductSessionOwner,
) -> Iterator[None]:
    """Pin existing state for one exact read and recheck Product authority."""
    product.assert_private_data_read_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor():
        yield
    product.assert_private_data_read_authority_current()


class PosixPrivateDataReadAuthority(NamedTuple):
    epoch: PackageProductPosixFencedRuntimeOwner
    state_root: Path
    state_identity: tuple[int, int]
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger


def assert_private_read_workspace(
    workspace: Path, identity: tuple[int, int], *, label: str
) -> None:
    assert_workspace_directory_identity(
        workspace, identity, changed=lambda: ValueError(f"{label} read workspace changed")
    )


@contextmanager
def prepare_posix_private_data_reader(
    workspace: Path,
    workspace_identity: tuple[int, int],
    *,
    authority_root: Path,
    control_root: Path,
    store_id: str,
    epochs_root_name: str,
    label: str,
) -> Iterator[PosixPrivateDataReadAuthority]:
    """Open existing state and transfer the epoch after successful construction."""
    epoch = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=authority_root,
        control_root=control_root,
        store_id=store_id,
        epochs_root_name=epochs_root_name,
        read_only=True,
    )
    try:
        assert_private_read_workspace(workspace, workspace_identity, label=label)
        state_root = epoch.control_root / "product-state"
        state_identity = private_product_state_identity(
            state_root, unsafe_message=f"{label} read Product state is unsafe"
        )
        binding = bind_read_only_product_desired_state(state_root)
        epoch.assert_current()
        assert_private_read_workspace(workspace, workspace_identity, label=label)
        yield PosixPrivateDataReadAuthority(
            epoch, state_root, state_identity, binding.gc_reservations, binding.desired
        )
    except BaseException:
        epoch.close()
        raise


def assert_private_read_current(
    epoch: PackageProductPosixFencedRuntimeOwner,
    workspace: Path,
    workspace_identity: tuple[int, int],
    state_root: Path,
    state_identity: tuple[int, int],
    *,
    label: str,
) -> None:
    assert_private_read_workspace(workspace, workspace_identity, label=label)
    epoch.assert_current()
    message = f"{label} read Product state changed"
    if private_product_state_identity(state_root, unsafe_message=message) != state_identity:
        raise ValueError(message)


@contextmanager
def private_data_read_fence(
    epoch: PackageProductPosixFencedRuntimeOwner,
    workspace: Path,
    workspace_identity: tuple[int, int],
    state_root: Path,
    state_identity: tuple[int, int],
    gc_gate: PluginPackageGcReservationJournal,
    desired_state: PluginDesiredStateLedger,
    *,
    label: str,
) -> Iterator[None]:
    """Pin existing runtime and Desired state using observation-only locks."""

    def assert_current() -> None:
        assert_private_read_current(
            epoch,
            workspace,
            workspace_identity,
            state_root,
            state_identity,
            label=label,
        )

    assert_current()
    registry = epoch.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id, read_only=True
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(f"{label} private-data Product runtime is active")
        assert_current()
        with gc_gate.read_guard():
            assert_current()
            desired_state.capture_read_only()
            try:
                yield
            finally:
                assert_current()
