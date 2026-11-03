"""Publish the six Windows Worker bases without switching history authority.

Each file is immutable and source-bound. Interrupted publication can finish
only the same bytes after the old Product evidence is reproved. Ordinary
readers and Package GC reject a remaining base stage.
"""

from __future__ import annotations

import os
from typing import Protocol

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_windows_base_files import WINDOWS_WORKER_BASE_FILES
from .package_product_worker_windows_checkpoint import (
    _CHECKPOINT_NAME,
    CodingWindowsWorkerHistoryCheckpointV1,
    _current_checkpoint_under_guard,
)
from .package_product_worker_windows_checkpoint import (
    _MAX_BYTES as _MAX_CHECKPOINT_BYTES,
)
from .package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .package_product_worker_windows_package_references import (
    _review_coding_windows_worker_package_references_under_guard,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


class _SemanticBase(Protocol):
    @property
    def record_digest(self) -> str: ...

    def to_bytes(self) -> bytes: ...


def _guarded_bases(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    publish: bool,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker bases require their Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker bases runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            checkpoint_path = product.state_root / _CHECKPOINT_NAME
            published_checkpoint = read_windows_private_receipt(
                checkpoint_path, maximum_bytes=_MAX_CHECKPOINT_BYTES
            )
            if published_checkpoint is None:
                raise ValueError("Windows Worker bases checkpoint is absent")
            checkpoint = CodingWindowsWorkerHistoryCheckpointV1.from_bytes(
                published_checkpoint
            )
            gc_snapshot = product.gc_gate.snapshot()
            current = _current_checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=False,
                allow_base_stage=publish,
            )
            if checkpoint != current:
                raise ValueError("Windows Worker bases checkpoint changed")
            review, prepared, semantic = (
                _review_coding_windows_worker_package_references_under_guard(
                    product,
                    quiescence=quiescence,
                    gc_snapshot=gc_snapshot,
                    allow_base_stage=publish,
                )
            )
            if (
                semantic.source_snapshot != checkpoint.source_snapshot
                or prepared.record_digest != checkpoint.preparation_digest
                or review.review_digest != checkpoint.package_reference_digest
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
                prepared, semantic
            )
            bases: tuple[_SemanticBase, ...] = (
                joined.opt_in,
                joined.receipt,
                joined.supervisor,
                joined.c5,
                joined.launch_intent,
                joined.native_provisioning,
            )
            if checkpoint.base_digests != tuple(
                (key, base.record_digest)
                for (key, _), base in zip(WINDOWS_WORKER_BASE_FILES, bases, strict=True)
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            expected = tuple(
                (product.state_root / name, base.to_bytes())
                for (_, name), base in zip(
                    WINDOWS_WORKER_BASE_FILES, bases, strict=True
                )
            )
            retained_bases: list[bytes | None] = []
            for path, raw in expected:
                retained = read_windows_private_receipt(
                    path,
                    maximum_bytes=_MAX_BASE_BYTES,
                    allow_unpublished_stage=publish,
                )
                staged = (
                    read_windows_private_receipt(
                        path.with_name(path.name + ".stage"),
                        maximum_bytes=_MAX_BASE_BYTES,
                    )
                    if publish
                    else None
                )
                if (retained is not None and retained != raw) or (
                    staged is not None and staged != raw
                ):
                    raise ValueError("Windows Worker base source changed")
                retained_bases.append(retained)
            if not publish and any(raw is None for raw in retained_bases):
                raise ValueError("Windows Worker base is absent")
            if publish:
                for (path, raw), retained in zip(expected, retained_bases, strict=True):
                    if retained is None:
                        write_windows_private_receipt(
                            path, raw, maximum_bytes=_MAX_BASE_BYTES
                        )
            if any(
                read_windows_private_receipt(path, maximum_bytes=_MAX_BASE_BYTES) != raw
                for path, raw in expected
            ):
                raise ValueError("Windows Worker base publication changed")
            if (
                read_windows_private_receipt(
                    checkpoint_path, maximum_bytes=_MAX_CHECKPOINT_BYTES
                )
                != published_checkpoint
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            product.assert_root_gc_authority_current()
            return checkpoint


def publish_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Write exact typed bases after the canonical checkpoint is published."""

    return _guarded_bases(product, publish=True)


def read_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Reprove all six published bases without writing Product state."""

    return _guarded_bases(product, publish=False)


__all__ = [
    "publish_coding_windows_worker_history_bases",
    "read_coding_windows_worker_history_bases",
]
