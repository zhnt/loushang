"""Read Windows Worker semantic bases without trusting retired source journals.

The checkpoint and all six immutable bases must agree before a later Product
owner can consider switching readers. This reader grants no cutover or deletion.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from loushang.harness.package_product._windows_worker_history import (
    capture_windows_product_worker_persisted_history,
)
from loushang.harness.package_product._worker_windows_attempt import (
    read_windows_product_worker_persisted_bases,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_persisted import (
    _WindowsPersistedBasesMethods,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
)
from .product_worker_windows_c5_base import CodingWindowsWorkerC5SemanticBaseV1
from .product_worker_windows_checkpoint import (
    _CHECKPOINT_NAME,
    CodingWindowsWorkerHistoryCheckpointV1,
)
from .product_worker_windows_checkpoint import _MAX_BYTES as _MAX_CHECKPOINT_BYTES
from .product_worker_windows_gc_history import _history_names
from .product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .product_worker_windows_launch_intent_base import (
    CodingWindowsWorkerLaunchIntentSemanticBaseV1,
)
from .product_worker_windows_opt_in_base import CodingWindowsWorkerOptInSemanticBaseV1
from .product_worker_windows_provisioning_base import (
    CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
)
from .product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)
from .product_worker_windows_supervisor_base import (
    CodingWindowsWorkerSupervisorSemanticBaseV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024
_MAX_CUTOVER_BYTES = 4096

if TYPE_CHECKING:
    from .product_worker_windows_history_cutover_record import (
        CodingWindowsWorkerHistoryCutoverRecordV1,
    )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPersistedBasesV1(_WindowsPersistedBasesMethods):
    _checkpoint_type = CodingWindowsWorkerHistoryCheckpointV1
    _join_type = CodingWindowsWorkerHistorySemanticJoinV1

    checkpoint: CodingWindowsWorkerHistoryCheckpointV1
    opt_in: CodingWindowsWorkerOptInSemanticBaseV1
    receipt: CodingWindowsWorkerReceiptSemanticBaseV1
    supervisor: CodingWindowsWorkerSupervisorSemanticBaseV1
    c5: CodingWindowsWorkerC5SemanticBaseV1
    launch_intent: CodingWindowsWorkerLaunchIntentSemanticBaseV1
    native_provisioning: CodingWindowsWorkerNativeProvisioningSemanticBaseV1


def _read_coding_windows_worker_persisted_bases(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    require_cutover: bool,
) -> tuple[
    CodingWindowsWorkerPersistedBasesV1,
    CodingWindowsWorkerHistoryCutoverRecordV1 | None,
]:
    """Read one Product snapshot under quiescence, its GC gate, and pinned root."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker persisted bases require their Product")
    result, marker = capture_windows_product_worker_persisted_history(
        product,
        read_under_guard=_read_coding_windows_worker_persisted_bases_under_gc_guard,
        require_cutover=require_cutover,
    )
    return result, cast("CodingWindowsWorkerHistoryCutoverRecordV1 | None", marker)


def _read_coding_windows_worker_persisted_bases_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    *,
    require_cutover: bool,
) -> tuple[
    CodingWindowsWorkerPersistedBasesV1,
    CodingWindowsWorkerHistoryCutoverRecordV1 | None,
]:
    """Read a pinned root while its caller holds the Product GC gate."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(root) is not int
        or root < 0
    ):
        raise ValueError("Windows Worker persisted bases require their Product")
    return read_windows_product_worker_persisted_bases(
        product,
        root,
        require_cutover=require_cutover,
        io=_receipt_io,
        history_names=_history_names(),
        checkpoint_name=_CHECKPOINT_NAME,
        base_files=WINDOWS_WORKER_BASE_FILES,
        cutover_name=WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
        limits=lambda: (_MAX_CHECKPOINT_BYTES, _MAX_BASE_BYTES, _MAX_CUTOVER_BYTES),
        decode_checkpoint=CodingWindowsWorkerHistoryCheckpointV1.from_bytes,
        make_result=CodingWindowsWorkerPersistedBasesV1._from_retained_bytes,
        cutover_codec=_persisted_cutover_codec,
    )


def _persisted_cutover_codec() -> Callable[
    [bytes, CodingWindowsWorkerPersistedBasesV1],
    CodingWindowsWorkerHistoryCutoverRecordV1,
]:
    from .product_worker_windows_history_cutover_record import (
        CodingWindowsWorkerHistoryCutoverRecordV1,
    )

    def decode(
        raw: bytes, bases: CodingWindowsWorkerPersistedBasesV1
    ) -> CodingWindowsWorkerHistoryCutoverRecordV1:
        cutover = CodingWindowsWorkerHistoryCutoverRecordV1.from_bytes(raw)
        cutover.require_persisted_bases(bases)
        return cutover

    return decode


def read_coding_windows_worker_persisted_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerPersistedBasesV1:
    """Validate pre-cutover bases without accepting a cutover marker."""

    result, _ = _read_coding_windows_worker_persisted_bases(
        product, require_cutover=False
    )
    return result


def read_coding_windows_worker_persisted_cutover(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[
    CodingWindowsWorkerHistoryCutoverRecordV1,
    CodingWindowsWorkerPersistedBasesV1,
]:
    """Validate a visible marker and bases together, without old journals."""

    result, marker = _read_coding_windows_worker_persisted_bases(
        product, require_cutover=True
    )
    if marker is None:
        raise ValueError("Windows Worker cutover marker is absent")
    return marker, result


__all__ = [
    "CodingWindowsWorkerPersistedBasesV1",
    "read_coding_windows_worker_persisted_bases",
    "read_coding_windows_worker_persisted_cutover",
]
