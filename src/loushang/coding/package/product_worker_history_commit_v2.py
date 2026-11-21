"""Commit the single Product Worker V2 owner after physical cutover proof.

The caller must hold Product runtime quiescence, the GC write gate, and a
pinned state root. This primitive additionally locks the five existing stream
locks in fixed order. The owner file is the only authority transition.
"""

from __future__ import annotations

from typing import cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product._linux_worker_history import (
    commit_product_history_owner,
    valid_history_cutoffs,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_history_cutover_v2 import CodingWorkerProductCutoverIndexV2
from .product_worker_history_preflight_v2 import CodingWorkerCutoverPreflightError
from .product_worker_history_prepared_v2 import CodingWorkerPreparedProductCutoverV2
from .product_worker_history_read_v2 import _HISTORY_PUBLICATION
from .product_worker_history_retention import _history_proof_bindings


class CodingWorkerV2OwnerCommitError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def commit_coding_worker_v2_owner_under_guard(
    rooted: RootedFile, *, prepared: CodingWorkerPreparedProductCutoverV2
) -> CodingWorkerProductCutoverIndexV2:
    """Publish one durable owner; a retry may only accept that exact owner."""
    return cast(
        CodingWorkerProductCutoverIndexV2,
        _HISTORY_PUBLICATION.commit_under_guard(
            rooted,
            prepared=prepared,
            error_type=CodingWorkerV2OwnerCommitError,
        ),
    )


def commit_coding_product_worker_v2_owner(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerProductCutoverIndexV2:
    """Reprove staged Product facts under custody, then publish one owner."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or not valid_history_cutoffs(first_retained_generations)
    ):
        raise ValueError(
            "Coding Worker V2 owner commit requires its Product and cutoffs"
        )
    return cast(
        CodingWorkerProductCutoverIndexV2,
        commit_product_history_owner(
            _history_proof_bindings(),
            product,
            publication=_HISTORY_PUBLICATION,
            prepared_type=CodingWorkerPreparedProductCutoverV2,
            preflight_error_type=CodingWorkerCutoverPreflightError,
            commit_error_type=CodingWorkerV2OwnerCommitError,
            first_retained_generations=first_retained_generations,
        ),
    )


__all__ = [
    "CodingWorkerV2OwnerCommitError",
    "commit_coding_product_worker_v2_owner",
    "commit_coding_worker_v2_owner_under_guard",
]
