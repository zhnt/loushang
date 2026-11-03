"""Package GC admits only a physically verified Worker V2 owner."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_worker_history_commit_v2 import (
    commit_coding_worker_v2_owner_under_guard,
)
from loushang.coding.package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from loushang.coding.package_product_worker_history_read_v2 import (
    CodingWorkerV2ReadError,
)
from loushang.coding.package_product_worker_history_segments import (
    _head_name,
    _segment_name,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
)
from loushang.coding.package_product_worker_posix_gc_history import (
    CodingPosixWorkerGcHistoryAuthority,
    _require_committed_v2_history,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_commit_v2 import _locks
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product GC")
def test_v2_gc_requires_five_streams_before_old_attempt_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _require_committed_v2_history(state_root=tmp_path, root_fd=root_fd)
    finally:
        os.close(root_fd)

    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", tmp_path)
    object.__setattr__(product, "policy", SimpleNamespace(product_id="coding"))

    @contextmanager
    def pinned(_self: PosixLocalWheelProductSessionOwner) -> Iterator[int]:
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(
        PosixLocalWheelProductSessionOwner,
        "assert_root_gc_authority_current",
        lambda _self: None,
    )
    monkeypatch.setattr(
        PosixLocalWheelProductSessionOwner, "pinned_state_root_gc_read", pinned
    )
    with _rooted(tmp_path) as rooted:
        rooted.sibling(_head_name("worker-supervisor", 1)).atomic_write(b"{}")
    authority = CodingPosixWorkerGcHistoryAuthority(product)
    with pytest.raises(CodingWorkerV2ReadError, match="active_head_changed"):
        authority.require_settled(observed_names=tuple(os.listdir(tmp_path)))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product GC")
def test_v2_gc_accepts_exact_deletion_debt_but_refuses_unlogged_loss(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    with _rooted(tmp_path) as rooted:
        stem = "worker-supervisor"
        rooted.sibling(_segment_name(stem, 0)).unlink()
        rooted.sibling(_head_name(stem, 0)).unlink()
        with pytest.raises(CodingWorkerV2ReadError, match="retained_segment_missing"):
            _require_committed_v2_history_for_test(tmp_path)
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        _require_committed_v2_history_for_test(tmp_path)


def _require_committed_v2_history_for_test(state_root: Path) -> None:
    root_fd = os.open(state_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _require_committed_v2_history(state_root=state_root, root_fd=root_fd)
    finally:
        os.close(root_fd)
