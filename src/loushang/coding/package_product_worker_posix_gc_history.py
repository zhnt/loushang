"""Read-only Linux Worker history proof for Product Package GC.

This authorizes only Package root deletion after complete attempt settlement.
It keeps every Worker journal and grants no history pruning authority.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loushang.harness.package_product._linux_worker_history import (
    require_committed_v2_history,
    require_settled_history,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_retention import _history_proof_bindings
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
)


def _require_committed_v2_history(
    *, state_root: Path, root_fd: int
) -> CodingWorkerNoEffectArchiveV2 | None:
    """Prove the committed Product owner and all five retained streams."""

    return require_committed_v2_history(
        _history_proof_bindings(), state_root=state_root, root_fd=root_fd
    )


class CodingPosixWorkerGcHistoryAuthority:
    """Join all retained Product attempts under the GC owner's existing guard."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not sys.platform.startswith("linux")
            or type(product) is not PosixLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Linux Worker GC requires its Product owner")
        self._product = product

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product

    def require_settled(self, *, observed_names: tuple[str, ...]) -> None:
        """Reject incomplete, orphaned, or changed Worker history without writes."""

        return require_settled_history(
            _history_proof_bindings(), self._product, observed_names=observed_names
        )


__all__ = ["CodingPosixWorkerGcHistoryAuthority"]
