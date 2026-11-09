"""Durable but non-authoritative Worker V2 Product preparation artifacts.

An intent is written before any artifact, so a crash leaves either no change
or a named, resumable V1-only preparation. The Product owner index is separate.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._preparation import (
    _MAX_BASE_BYTES as _MAX_BASE_BYTES,
)
from loushang.harness.worker.history._preparation import (
    _MAX_INDEX_BYTES as _MAX_INDEX_BYTES,
)
from loushang.harness.worker.history._preparation import (
    _MAX_INTENT_BYTES as _MAX_INTENT_BYTES,
)
from loushang.harness.worker.history._preparation import (
    _MAX_STREAM_BYTES as _MAX_STREAM_BYTES,
)
from loushang.harness.worker.history._preparation import (
    PreparationHistory,
    _PreparationIntentMethods,
)

from .package_product_worker_history_preflight_v2 import (
    _prepare_coding_product_worker_history_cutover_under_guard,
)
from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_v2_names import (
    PREPARATION_INTENT_NAME,
)


class CodingWorkerV2PreparationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerV2PreparationIntent(_PreparationIntentMethods):
    scope_id: str
    store_id: str
    checkpoint_digest: str
    index_digest: str
    artifact_digests: tuple[tuple[str, str], ...]
    record_digest: str
    version: int = 2

    _prepared_type = CodingWorkerPreparedProductCutoverV2


CodingWorkerV2PreparationIntent._wire_schema = (
    CodingWorkerV2PreparationIntent._make_wire_schema()
)
_PREPARATION_HISTORY = PreparationHistory(
    CodingWorkerPreparedProductCutoverV2,
    CodingWorkerV2PreparationIntent,
    CodingWorkerV2PreparationError,
)


def stage_coding_worker_v2_preparation(
    rooted: RootedFile, *, prepared: CodingWorkerPreparedProductCutoverV2
) -> CodingWorkerV2PreparationIntent:
    """Durably stage exact bytes; retries complete only the same intent."""
    return _PREPARATION_HISTORY.stage(
        rooted,
        prepared=prepared,
        max_intent_bytes=_MAX_INTENT_BYTES,
        max_base_bytes=_MAX_BASE_BYTES,
        max_stream_bytes=_MAX_STREAM_BYTES,
        max_index_bytes=_MAX_INDEX_BYTES,
    )


def read_coding_worker_v2_preparation(
    rooted: RootedFile,
) -> CodingWorkerPreparedProductCutoverV2 | None:
    """Verify all staged bytes; this never selects V2 as Product authority."""
    return _PREPARATION_HISTORY.read(
        rooted,
        max_intent_bytes=_MAX_INTENT_BYTES,
        max_base_bytes=_MAX_BASE_BYTES,
        max_stream_bytes=_MAX_STREAM_BYTES,
        max_index_bytes=_MAX_INDEX_BYTES,
    )


def rollback_coding_worker_v2_preparation(rooted: RootedFile) -> bool:
    """Remove only intent-owned bytes while no Product owner index exists."""
    return _PREPARATION_HISTORY.rollback(
        rooted,
        max_intent_bytes=_MAX_INTENT_BYTES,
        max_base_bytes=_MAX_BASE_BYTES,
        max_stream_bytes=_MAX_STREAM_BYTES,
        max_index_bytes=_MAX_INDEX_BYTES,
    )


def stage_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerV2PreparationIntent:
    """Prepare and stage under the same Product runtime and GC custody."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 staging requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            prepared = _prepare_coding_product_worker_history_cutover_under_guard(
                product,
                first_retained_generations=first_retained_generations,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                with RootedFileIO(product.state_root, root_fd) as file_io:
                    with file_io.bind(
                        product.state_root / PREPARATION_INTENT_NAME, durable=True
                    ) as rooted:
                        result = stage_coding_worker_v2_preparation(
                            rooted, prepared=prepared
                        )
            product.assert_root_gc_authority_current()
            return result


def rollback_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Remove only matching staged bytes while V1 still owns all history."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 rollback requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id):
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                with RootedFileIO(product.state_root, root_fd) as file_io:
                    with file_io.bind(
                        product.state_root / PREPARATION_INTENT_NAME, durable=True
                    ) as rooted:
                        result = rollback_coding_worker_v2_preparation(rooted)
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2PreparationError",
    "CodingWorkerV2PreparationIntent",
    "read_coding_worker_v2_preparation",
    "rollback_coding_product_worker_v2_preparation",
    "rollback_coding_worker_v2_preparation",
    "stage_coding_product_worker_v2_preparation",
    "stage_coding_worker_v2_preparation",
]
