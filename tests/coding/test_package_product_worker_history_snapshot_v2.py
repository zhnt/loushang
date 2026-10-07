"""V2 snapshots preserve checkpoint fingerprints after retired bytes leave disk."""

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
from loushang.coding.package_product_worker_history_segments import (
    _head_name,
    _segment_name,
    commit_coding_worker_active_segment,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
    capture_coding_worker_history_streams_under_gc_guard,
    verify_coding_worker_history_stream_extensions_under_gc_guard,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
)
from loushang.coding.package_product_worker_opt_in import _opt_in_line
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_commit_v2 import _locks
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_opt_in_base_v2 import _allow


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Worker V2")
def test_v2_snapshot_preserves_old_checkpoint_after_retirement_and_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    histories = _sources()[2]
    baseline = tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        for stem, history in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
        )
    )
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)

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
    assert capture_coding_worker_history_streams_under_gc_guard(product) == baseline

    with _rooted(tmp_path) as rooted:
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            rooted.sibling(_segment_name(stem, 0)).unlink()
            rooted.sibling(_head_name(stem, 0)).unlink()
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
    assert capture_coding_worker_history_streams_under_gc_guard(product) == baseline
    assert verify_coding_worker_history_stream_extensions_under_gc_guard(
        product, previous=baseline, current=baseline
    )

    with _rooted(tmp_path) as rooted:
        stem = "worker-opt-in"
        active = rooted.sibling(_segment_name(stem, 1))
        previous_raw = active.read_bytes(max_bytes=32 * 1024 * 1024)
        line = _opt_in_line(
            _allow(
                plugin_id="plugin-b",
                revision=5,
                generation=2,
                kill=0,
                operation="allow-b2",
            )
        )
        active.append_bytes(line)
        commit_coding_worker_active_segment(
            rooted,
            stem=stem,
            stream_id=stem,
            generation=1,
            previous_raw=previous_raw,
            appended_line=line,
        )
    current = capture_coding_worker_history_streams_under_gc_guard(product)
    assert current[0].total_revision == baseline[0].total_revision + 1
    assert verify_coding_worker_history_stream_extensions_under_gc_guard(
        product, previous=baseline, current=current
    )
    wrong_opt_in = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem="worker-opt-in",
        active_generation=histories[0].active_generation,
        last_sealed_revision=histories[0].last_sealed_revision,
        segments=(histories[0].segments[0], histories[0].segments[1] + b" "),
    )
    assert not verify_coding_worker_history_stream_extensions_under_gc_guard(
        product, previous=(wrong_opt_in, *baseline[1:]), current=current
    )
    assert not verify_coding_worker_history_stream_extensions_under_gc_guard(
        product, previous=current, current=baseline
    )
