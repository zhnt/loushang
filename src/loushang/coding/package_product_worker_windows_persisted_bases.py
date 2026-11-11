"""Read Windows Worker semantic bases without trusting retired source journals.

The checkpoint and all six immutable bases must agree before a later Product
owner can consider switching readers. This reader grants no cutover or deletion.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.harness.package_product._worker_windows_attempt import (
    read_windows_product_worker_persisted_bases,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_legacy_windows_receipt import _receipt_io
from .package_product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
)
from .package_product_worker_windows_c5_base import (
    CodingWindowsWorkerC5SemanticBaseV1,
)
from .package_product_worker_windows_checkpoint import (
    _CHECKPOINT_NAME,
    CodingWindowsWorkerHistoryCheckpointV1,
)
from .package_product_worker_windows_checkpoint import (
    _MAX_BYTES as _MAX_CHECKPOINT_BYTES,
)
from .package_product_worker_windows_gc_history import (
    _history_names,
)
from .package_product_worker_windows_launch_intent_base import (
    CodingWindowsWorkerLaunchIntentSemanticBaseV1,
)
from .package_product_worker_windows_opt_in_base import (
    CodingWindowsWorkerOptInSemanticBaseV1,
)
from .package_product_worker_windows_provisioning_base import (
    CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
)
from .package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)
from .package_product_worker_windows_supervisor_base import (
    CodingWindowsWorkerSupervisorSemanticBaseV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024
_MAX_CUTOVER_BYTES = 4096

if TYPE_CHECKING:
    from .package_product_worker_windows_history_cutover_record import (
        CodingWindowsWorkerHistoryCutoverRecordV1,
    )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPersistedBasesV1:
    checkpoint: CodingWindowsWorkerHistoryCheckpointV1
    opt_in: CodingWindowsWorkerOptInSemanticBaseV1
    receipt: CodingWindowsWorkerReceiptSemanticBaseV1
    supervisor: CodingWindowsWorkerSupervisorSemanticBaseV1
    c5: CodingWindowsWorkerC5SemanticBaseV1
    launch_intent: CodingWindowsWorkerLaunchIntentSemanticBaseV1
    native_provisioning: CodingWindowsWorkerNativeProvisioningSemanticBaseV1

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not CodingWindowsWorkerHistoryCheckpointV1:
            raise ValueError("Windows Worker persisted bases are invalid")
        source = self.checkpoint.source_snapshot
        bases = (
            ("optIn", self.opt_in, CodingWindowsWorkerOptInSemanticBaseV1),
            ("receipt", self.receipt, CodingWindowsWorkerReceiptSemanticBaseV1),
            (
                "supervisor",
                self.supervisor,
                CodingWindowsWorkerSupervisorSemanticBaseV1,
            ),
            ("c5", self.c5, CodingWindowsWorkerC5SemanticBaseV1),
            (
                "launchIntent",
                self.launch_intent,
                CodingWindowsWorkerLaunchIntentSemanticBaseV1,
            ),
            (
                "nativeProvisioning",
                self.native_provisioning,
                CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
            ),
        )
        if (
            any(
                type(base) is not expected
                or base.scope_id != source.scope_id
                or base.store_id != source.store_id
                or base.source_snapshot_digest != source.snapshot_digest
                for _, base, expected in bases
            )
            or self.checkpoint.base_digests
            != tuple((name, base.record_digest) for name, base, _ in bases)
            or self.checkpoint.opt_in_operation_ids != self.opt_in.retired_operation_ids
            or self.checkpoint.receipt_fingerprints
            != self.receipt.retired_receipt_fingerprints
            or self.checkpoint.native_provisioning_attempt_ids
            != self.native_provisioning.attempt_ids
            or not set(self.native_provisioning.attempt_ids).issubset(
                self.c5.known_attempt_ids
            )
            or not set(self.supervisor.retired_attempt_ids).issubset(
                self.launch_intent.intent_attempt_ids
            )
            or not set(self.launch_intent.intent_attempt_ids).issubset(
                self.native_provisioning.attempt_ids
            )
            or not set(self.native_provisioning.attempt_ids).issubset(
                self.checkpoint.attempt_ids
            )
        ):
            raise ValueError("Windows Worker persisted bases are invalid")


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
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker persisted bases runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                result = _read_coding_windows_worker_persisted_bases_under_gc_guard(
                    product, root, require_cutover=require_cutover
                )
            product.assert_root_gc_authority_current()
            return result


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
        make_result=lambda checkpoint, raw: CodingWindowsWorkerPersistedBasesV1(
            checkpoint=checkpoint,
            opt_in=CodingWindowsWorkerOptInSemanticBaseV1.from_bytes(raw[0]),
            receipt=CodingWindowsWorkerReceiptSemanticBaseV1.from_bytes(raw[1]),
            supervisor=CodingWindowsWorkerSupervisorSemanticBaseV1.from_bytes(raw[2]),
            c5=CodingWindowsWorkerC5SemanticBaseV1.from_bytes(raw[3]),
            launch_intent=CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_bytes(
                raw[4]
            ),
            native_provisioning=CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_bytes(
                raw[5]
            ),
        ),
        cutover_codec=_persisted_cutover_codec,
    )


def _persisted_cutover_codec() -> Callable[
    [bytes, CodingWindowsWorkerPersistedBasesV1],
    CodingWindowsWorkerHistoryCutoverRecordV1,
]:
    from .package_product_worker_windows_history_cutover_record import (
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
