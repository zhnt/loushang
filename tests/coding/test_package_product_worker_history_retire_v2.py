"""V2 retirement writes deletion debt before removing any sealed source."""

from __future__ import annotations

import os
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
    read_coding_worker_v2_retained_history,
)
from loushang.coding.package_product_worker_history_retire_v2 import (
    CodingWorkerV2RetirementError,
    retire_coding_product_worker_v2_history,
    retire_coding_worker_v2_history_under_guard,
)
from loushang.coding.package_product_worker_history_segments import (
    _head_name,
    _segment_name,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    capture_coding_worker_history_streams_under_gc_guard,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
)
from loushang.coding.package_product_worker_posix_gc_history import (
    _require_committed_v2_history,
)
from loushang.harness.journal._rooted_io import RootedFile
from tests.coding.test_package_product_worker_history_commit_v2 import (
    _locks,
    _product,
)
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted


def _committed(tmp_path: Path) -> CodingWorkerV2DeletionLedger:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    return CodingWorkerV2DeletionLedger.from_prepared(prepared)


def test_v2_retirement_deletes_only_owner_named_sealed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _committed(tmp_path)
    calls: list[str] = []
    product = _product(tmp_path, monkeypatch, calls)
    with _rooted(tmp_path) as rooted:
        before = tuple(
            read_coding_worker_v2_retained_history(rooted, stem=stem)
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )
    assert retire_coding_product_worker_v2_history(product)
    assert (tmp_path / DELETION_LEDGER_NAME).read_bytes() == ledger.to_bytes()
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        assert not (tmp_path / _segment_name(stem, 0)).exists()
        assert not (tmp_path / _head_name(stem, 0)).exists()
        assert (tmp_path / _segment_name(stem, 1)).exists()
    with _rooted(tmp_path) as rooted:
        after = tuple(
            read_coding_worker_v2_retained_history(rooted, stem=stem)
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )
    assert after == before
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _require_committed_v2_history(state_root=tmp_path, root_fd=root_fd)
    finally:
        os.close(root_fd)
    assert capture_coding_worker_history_streams_under_gc_guard(product) == (
        _sources()[0][-1].stream_snapshots
    )
    assert not retire_coding_product_worker_v2_history(product)
    assert calls == ["runtime-enter", "gc-enter", "gc-exit", "runtime-exit"] * 2


def test_v2_retirement_resumes_after_first_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _committed(tmp_path)
    original_unlink = RootedFile.unlink_owned
    interrupted_name = _head_name("worker-opt-in", 0)

    def pause(self: RootedFile, identity: tuple[int, int]) -> None:
        if self._name == interrupted_name:
            raise OSError("injected retirement pause")
        original_unlink(self, identity)

    with _rooted(tmp_path) as rooted:
        with monkeypatch.context() as interrupted:
            interrupted.setattr(RootedFile, "unlink_owned", pause)
            with pytest.raises(OSError, match="retirement pause"):
                retire_coding_worker_v2_history_under_guard(rooted)
    assert (tmp_path / DELETION_LEDGER_NAME).read_bytes() == ledger.to_bytes()
    assert not (tmp_path / _segment_name("worker-opt-in", 0)).exists()
    assert (tmp_path / interrupted_name).exists()
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(
                rooted, stem="worker-opt-in"
            ).last_revision
            > 0
        )
        assert retire_coding_worker_v2_history_under_guard(rooted)
    assert not (tmp_path / interrupted_name).exists()


def test_v2_retirement_refuses_uncommitted_sources(tmp_path: Path) -> None:
    with _rooted(tmp_path) as rooted:
        _write_sources(rooted)
        _locks(rooted)
        with pytest.raises(CodingWorkerV2ReadError, match="owner_absent"):
            retire_coding_worker_v2_history_under_guard(rooted)
    assert not (tmp_path / DELETION_LEDGER_NAME).exists()
    assert (tmp_path / _segment_name("worker-opt-in", 0)).exists()


def test_v2_retirement_refuses_changed_source_and_ledger(tmp_path: Path) -> None:
    _committed(tmp_path)
    stem = "worker-supervisor"
    with _rooted(tmp_path) as rooted:
        source = rooted.sibling(_segment_name(stem, 0))
        original = source.read_bytes(max_bytes=32 * 1024 * 1024)
        source.atomic_write(b"changed\n")
        with pytest.raises(CodingWorkerV2ReadError, match="sealed_segment_changed"):
            retire_coding_worker_v2_history_under_guard(rooted)
        assert not (tmp_path / DELETION_LEDGER_NAME).exists()
        source.atomic_write(original)
    with _rooted(tmp_path) as rooted:
        rooted.sibling(DELETION_LEDGER_NAME).create_new(b"{}")
        with pytest.raises(ValueError, match="deletion ledger"):
            retire_coding_worker_v2_history_under_guard(rooted)
    assert (tmp_path / _segment_name(stem, 0)).read_bytes() == original


def test_product_v2_retirement_refuses_active_runtime_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _committed(tmp_path)
    calls: list[str] = []
    product = _product(tmp_path, monkeypatch, calls)

    class ActiveRegistry:
        store_id = "store"

        @contextmanager
        def exclusive_runtime_quiescence(
            self, *, store_id: str
        ) -> Iterator[SimpleNamespace]:
            assert store_id == self.store_id
            yield SimpleNamespace(active_runtime_lease_ids=("lease",))

    object.__setattr__(
        product, "epoch_runtime", SimpleNamespace(registry=ActiveRegistry())
    )
    with pytest.raises(CodingWorkerV2RetirementError, match="runtime_active"):
        retire_coding_product_worker_v2_history(product)
    assert not (tmp_path / DELETION_LEDGER_NAME).exists()
    assert (tmp_path / _segment_name("worker-opt-in", 0)).exists()
    assert calls == []
