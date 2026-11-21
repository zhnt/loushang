"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from contextlib import contextmanager

from loushang.coding.package import private_data_deletion_preview as _binding


@contextmanager
def offline(
    self: _binding.CodingArchPrivateDataDeletionPreview,
) -> _binding.Iterator[None]:
    registry = self.product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
        self.product.assert_root_gc_authority_current()
        with self.product.gc_gate.guard():
            yield
        self.product.assert_root_gc_authority_current()
