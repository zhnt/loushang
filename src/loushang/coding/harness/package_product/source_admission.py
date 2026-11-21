"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.package import product_runtime as _binding


def capture_inert_source(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    source: _binding.Path,
    kind: Literal["data", "dependency"],
) -> (
    _binding.CodingExternalDataWheelBindingV1
    | _binding.CodingExternalDependencyWheelBindingV1
):
    """Capture one inert source through the original epoch and catalog owners."""
    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    try:
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError(_binding._SOURCE_ADMISSION_PROGRAM_VALUES["value_001"])
        return (
            _binding.CodingExternalDataWheelCatalog
            if kind == "data"
            else _binding.CodingExternalDependencyWheelCatalog
        )(
            epoch_runtime.prepare_product_state_root()
            / (
                _binding._SOURCE_ADMISSION_PROGRAM_VALUES["value_002"]
                if kind == "data"
                else _binding._SOURCE_ADMISSION_PROGRAM_VALUES["value_003"]
            ),
            source_root=epoch_runtime.prepare_product_source_root(),
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, epoch_runtime=epoch_runtime)
    finally:
        epoch_runtime.close()


def capture_worker_source(
    lifecycle: _binding.CodingPluginLifecycleStateLayout,
    *,
    source: _binding.Path,
    admission: _binding.PackageProductLocalWorkerAdmissionV1,
) -> _binding.CodingExternalWorkerWheelBindingV1:
    """Capture one inert Worker candidate; the normal Session route stays dark."""

    epoch = _binding.resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        _binding.PackageProductWindowsFencedRuntimeOwner
        if _binding.os.name == "nt"
        else _binding.PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(**epoch.fenced_runtime_open_kwargs())
    try:
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError(_binding._SOURCE_ADMISSION_PROGRAM_VALUES["value_001"])
        if isinstance(epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner):
            return _binding.CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime,
                state_root=epoch_runtime.prepare_product_state_root(),
                source_root=epoch_runtime.prepare_product_source_root(),
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=lifecycle.scope_id,
            ).capture(source, admission=admission)
        return _binding.CodingExternalWorkerWheelCatalog(
            epoch_runtime.prepare_product_state_root()
            / _binding._SOURCE_ADMISSION_PROGRAM_VALUES["value_004"],
            source_root=epoch_runtime.prepare_product_source_root(),
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, admission=admission, epoch_runtime=epoch_runtime)
    finally:
        epoch_runtime.close()
