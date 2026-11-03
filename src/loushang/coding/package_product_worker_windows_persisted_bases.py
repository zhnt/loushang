"""Read Windows Worker semantic bases without trusting retired source journals.

The checkpoint and all six immutable bases must agree before a later Product
owner can consider switching readers. This reader grants no cutover or deletion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from .package_legacy_windows_receipt import (
    _read_file,
    _require_no_named_directory_streams,
    _require_simple_attributes,
)
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
    _require_known_windows_worker_state_names,
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
    product.assert_root_gc_authority_current()
    with WindowsPrivateDirectoryAcl() as acl:
        acl.validate(root)
        _require_simple_attributes(os.fstat(root), directory=True)
        _require_no_named_directory_streams(root)
        if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
            raise ValueError("Windows Worker persisted root changed")
        names = tuple(windows_listdir_at(root))
        if require_cutover:
            if names.count(WINDOWS_WORKER_HISTORY_CUTOVER_NAME) != 1:
                raise ValueError("Windows Worker cutover marker is absent")
            known_names = tuple(
                name for name in names if name != WINDOWS_WORKER_HISTORY_CUTOVER_NAME
            )
        else:
            known_names = names
        _require_known_windows_worker_state_names(known_names)
        if any(name.casefold().endswith(".stage") for name in names):
            raise ValueError("Windows Worker persisted stage remains")
        checkpoint_raw = _read_file(
            root, acl, _CHECKPOINT_NAME, maximum_bytes=_MAX_CHECKPOINT_BYTES
        )
        if checkpoint_raw is None:
            raise ValueError("Windows Worker persisted checkpoint is absent")
        checkpoint = CodingWindowsWorkerHistoryCheckpointV1.from_bytes(checkpoint_raw)
        raw_bases = tuple(
            _read_file(root, acl, name, maximum_bytes=_MAX_BASE_BYTES)
            for _, name in WINDOWS_WORKER_BASE_FILES
        )
        if any(raw is None for raw in raw_bases):
            raise ValueError("Windows Worker persisted base is absent")
        opt_in, receipt, supervisor, c5, launch_intent, native = (
            raw for raw in raw_bases if raw is not None
        )
        result = CodingWindowsWorkerPersistedBasesV1(
            checkpoint=checkpoint,
            opt_in=CodingWindowsWorkerOptInSemanticBaseV1.from_bytes(opt_in),
            receipt=CodingWindowsWorkerReceiptSemanticBaseV1.from_bytes(receipt),
            supervisor=CodingWindowsWorkerSupervisorSemanticBaseV1.from_bytes(
                supervisor
            ),
            c5=CodingWindowsWorkerC5SemanticBaseV1.from_bytes(c5),
            launch_intent=CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_bytes(
                launch_intent
            ),
            native_provisioning=CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_bytes(
                native
            ),
        )
        cutover = None
        cutover_raw = None
        if require_cutover:
            from .package_product_worker_windows_history_cutover_record import (
                CodingWindowsWorkerHistoryCutoverRecordV1,
            )

            cutover_raw = _read_file(
                root,
                acl,
                WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
                maximum_bytes=_MAX_CUTOVER_BYTES,
            )
            if cutover_raw is None:
                raise ValueError("Windows Worker cutover marker is absent")
            cutover = CodingWindowsWorkerHistoryCutoverRecordV1.from_bytes(cutover_raw)
            cutover.require_persisted_bases(result)
        if (
            _read_file(
                root,
                acl,
                _CHECKPOINT_NAME,
                maximum_bytes=_MAX_CHECKPOINT_BYTES,
            )
            != checkpoint_raw
            or tuple(
                _read_file(root, acl, name, maximum_bytes=_MAX_BASE_BYTES)
                for _, name in WINDOWS_WORKER_BASE_FILES
            )
            != raw_bases
            or (
                require_cutover
                and _read_file(
                    root,
                    acl,
                    WINDOWS_WORKER_HISTORY_CUTOVER_NAME,
                    maximum_bytes=_MAX_CUTOVER_BYTES,
                )
                != cutover_raw
            )
            or tuple(windows_listdir_at(root)) != names
            or not os.path.samestat(os.fstat(root), product.state_root.lstat())
        ):
            raise ValueError("Windows Worker persisted bases changed")
        acl.validate(root)
        _require_simple_attributes(os.fstat(root), directory=True)
        _require_no_named_directory_streams(root)
    product.assert_root_gc_authority_current()
    return result, cutover


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
