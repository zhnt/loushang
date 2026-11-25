"""Durable but non-authoritative Worker V2 Product preparation artifacts.

An intent is written before any artifact, so a crash leaves either no change
or a named, resumable V1-only preparation. The Product owner index is separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product._linux_worker_history import (
    rollback_product_history_preparation,
    stage_product_history_preparation,
)
from loushang.harness.package_product._worker_history_access import (
    is_exact_posix_worker_history_product,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._preparation import (
    PreparationHistory,
    _PreparationIntentMethods,
)

from .product_worker_history_preflight_v2 import CodingWorkerCutoverPreflightError
from .product_worker_history_prepared_v2 import CodingWorkerPreparedProductCutoverV2
from .product_worker_history_retention import _history_proof_bindings


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
    return _PREPARATION_HISTORY.stage(rooted, prepared=prepared)


def read_coding_worker_v2_preparation(
    rooted: RootedFile,
) -> CodingWorkerPreparedProductCutoverV2 | None:
    """Verify all staged bytes; this never selects V2 as Product authority."""
    return _PREPARATION_HISTORY.read(rooted)


def rollback_coding_worker_v2_preparation(rooted: RootedFile) -> bool:
    """Remove only intent-owned bytes while no Product owner index exists."""
    return _PREPARATION_HISTORY.rollback(rooted)


def stage_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerV2PreparationIntent:
    """Prepare and stage under the same Product runtime and GC custody."""

    if not is_exact_posix_worker_history_product(product, product_id="coding"):
        raise ValueError("Coding Worker V2 staging requires its Product")
    return cast(
        CodingWorkerV2PreparationIntent,
        stage_product_history_preparation(
            _history_proof_bindings(),
            product,
            prepared_type=CodingWorkerPreparedProductCutoverV2,
            error_type=CodingWorkerCutoverPreflightError,
            first_retained_generations=first_retained_generations,
        ),
    )


def rollback_coding_product_worker_v2_preparation(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Remove only matching staged bytes while V1 still owns all history."""

    if not is_exact_posix_worker_history_product(product, product_id="coding"):
        raise ValueError("Coding Worker V2 rollback requires its Product")
    return rollback_product_history_preparation(_history_proof_bindings(), product)


__all__ = [
    "CodingWorkerV2PreparationError",
    "CodingWorkerV2PreparationIntent",
    "read_coding_worker_v2_preparation",
    "rollback_coding_product_worker_v2_preparation",
    "rollback_coding_worker_v2_preparation",
    "stage_coding_product_worker_v2_preparation",
    "stage_coding_worker_v2_preparation",
]
