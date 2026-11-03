"""Durably retire only Worker V2 generations named by the Product owner."""

from __future__ import annotations

import sys
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from .package_product_worker_history_read_v2 import (
    _seal_head,
    read_coding_worker_v2_retained_history,
)
from .package_product_worker_history_segments import _head_name, _segment_name
from .package_product_worker_history_stage_v2 import (
    read_coding_worker_v2_preparation,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
)

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_HEAD_BYTES = 512
_MAX_LEDGER_BYTES = 1024 * 1024


class CodingWorkerV2RetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _optional(rooted: RootedFile, name: str, *, limit: int) -> bytes | None:
    try:
        return rooted.sibling(name).read_bytes(max_bytes=limit)
    except FileNotFoundError:
        return None


def _unlink_matching(
    rooted: RootedFile, *, name: str, expected: bytes, limit: int
) -> None:
    file = rooted.sibling(name)
    raw = _optional(rooted, name, limit=limit)
    if raw is None:
        return
    if raw != expected:
        raise CodingWorkerV2RetirementError("coding_worker_v2_retired_bytes_changed")
    observed = file.stat()
    file.unlink_owned((observed.st_dev, observed.st_ino))


def retire_coding_worker_v2_history_under_guard(rooted: RootedFile) -> bool:
    """Write exact deletion debt before unlinking any retired source bytes."""

    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        try:
            rooted.sibling(stem + ".jsonl.lock").acquire_lock(
                exclusive=True, suffix="", create=False
            )
        except FileNotFoundError as exc:
            raise CodingWorkerV2RetirementError(
                "coding_worker_v2_stream_lock_missing"
            ) from exc
    before = tuple(
        read_coding_worker_v2_retained_history(rooted, stem=stem)
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    prepared = read_coding_worker_v2_preparation(rooted)
    if prepared is None:
        raise CodingWorkerV2RetirementError("coding_worker_v2_preparation_absent")
    ledger = CodingWorkerV2DeletionLedger.from_prepared(prepared)
    current = _optional(rooted, DELETION_LEDGER_NAME, limit=_MAX_LEDGER_BYTES)
    if current is None:
        rooted.sibling(DELETION_LEDGER_NAME).create_new(ledger.to_bytes())
    elif current != ledger.to_bytes():
        raise CodingWorkerV2RetirementError("coding_worker_v2_deletion_ledger_changed")

    removed = False
    for stream in prepared.streams:
        for seal in stream.retired_sealed:
            name = _segment_name(stream.stem, seal.generation)
            raw = _optional(rooted, name, limit=_MAX_SEGMENT_BYTES)
            if raw is not None:
                if (
                    len(raw) != seal.byte_count
                    or sha256(raw).hexdigest() != seal.digest
                ):
                    raise CodingWorkerV2RetirementError(
                        "coding_worker_v2_retired_bytes_changed"
                    )
                _unlink_matching(
                    rooted, name=name, expected=raw, limit=_MAX_SEGMENT_BYTES
                )
                removed = True
            head_name = _head_name(stream.stem, seal.generation)
            if _optional(rooted, head_name, limit=_MAX_HEAD_BYTES) is not None:
                _unlink_matching(
                    rooted,
                    name=head_name,
                    expected=_seal_head(stream.stem, seal),
                    limit=_MAX_HEAD_BYTES,
                )
                removed = True
    after = tuple(
        read_coding_worker_v2_retained_history(rooted, stem=stem)
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    if after != before:
        raise CodingWorkerV2RetirementError("coding_worker_v2_retained_history_changed")
    return removed


def retire_coding_product_worker_v2_history(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Retire owner-authorized bytes under Product runtime and GC custody."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 retirement requires its Linux Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWorkerV2RetirementError("coding_worker_v2_runtime_active")
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                file_io = RootedFileIO(product.state_root, root_fd)
                try:
                    with file_io.bind(
                        product.state_root / DELETION_LEDGER_NAME, durable=True
                    ) as rooted:
                        result = retire_coding_worker_v2_history_under_guard(rooted)
                finally:
                    file_io.cleanup()
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2RetirementError",
    "retire_coding_product_worker_v2_history",
    "retire_coding_worker_v2_history_under_guard",
]
