"""Keep private-data operations inside their existing Product fences."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.workspace.paths import assert_workspace_directory_identity

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PosixLocalWheelProductSessionOwner,
    )
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )

    from .ledger import PluginDesiredStateLedger
    from .package_gc_reservation import PluginPackageGcReservationJournal


@contextmanager
def private_data_mutation_fence(
    product: PosixLocalWheelProductSessionOwner, *, label: str
) -> Iterator[None]:
    """Hold quiescence and the exclusive GC gate through a Product operation."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(f"{label} private-data Product runtime is active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard():
            yield
        product.assert_root_gc_authority_current()


def private_read_state_identity(state_root: Path, *, message: str) -> tuple[int, int]:
    metadata = state_root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError(message)
    return metadata.st_dev, metadata.st_ino


def assert_private_read_current(
    epoch: PackageProductPosixFencedRuntimeOwner,
    workspace: Path,
    workspace_identity: tuple[int, int],
    state_root: Path,
    state_identity: tuple[int, int],
    *,
    label: str,
) -> None:
    assert_workspace_directory_identity(
        workspace,
        workspace_identity,
        changed=lambda: ValueError(f"{label} read workspace changed"),
    )
    epoch.assert_current()
    message = f"{label} read Product state changed"
    if private_read_state_identity(state_root, message=message) != state_identity:
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
