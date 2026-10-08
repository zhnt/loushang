"""Product V2 preflight keeps closure and source reads in one custody period."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_history_preflight_v2 as preflight
from loushang.coding.package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    initialize_coding_worker_active_head,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    capture_coding_worker_history_streams_under_gc_guard,
    read_coding_worker_histories_under_gc_guard,
)
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources


def _product_stub(tmp_path: Path) -> PosixLocalWheelProductSessionOwner:
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", tmp_path)
    object.__setattr__(product, "policy", SimpleNamespace(product_id="coding"))
    return product


def test_product_stream_reader_reopens_five_strict_rooted_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        file_io = RootedFileIO(tmp_path, root_fd)
        try:
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                with file_io.bind(tmp_path / f"{stem}.jsonl", durable=True) as rooted:
                    rooted.create_new(b"")
                    initialize_coding_worker_active_head(
                        rooted, stem=stem, stream_id=stem
                    )
        finally:
            file_io.cleanup()
    finally:
        os.close(root_fd)
    product = _product_stub(tmp_path)

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
    histories = read_coding_worker_histories_under_gc_guard(product)
    assert len(histories) == 5
    assert all(history.segments == (b"",) for history in histories)
    assert all(
        item.total_revision == 0
        for item in capture_coding_worker_history_streams_under_gc_guard(product)
    )
    (tmp_path / "worker-supervisor.jsonl").write_bytes(b"{}\n")
    with pytest.raises(
        CodingWorkerHistorySegmentError, match="coding_worker_segment_head_changed"
    ):
        read_coding_worker_histories_under_gc_guard(product)


def test_product_preflight_refuses_open_closure_before_preparing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoints, _anchor, histories = _sources()
    checkpoint = checkpoints[-1]
    product = _product_stub(tmp_path)
    calls: list[str] = []

    class Registry:
        store_id = "store"

        @contextmanager
        def exclusive_runtime_quiescence(
            self, *, store_id: str
        ) -> Iterator[SimpleNamespace]:
            assert store_id == self.store_id
            calls.append("runtime-enter")
            try:
                yield SimpleNamespace(active_runtime_lease_ids=())
            finally:
                calls.append("runtime-exit")

    class GcGate:
        @contextmanager
        def guard(self, *, require_write: bool) -> Iterator[None]:
            assert require_write
            calls.append("gc-enter")
            try:
                yield
            finally:
                calls.append("gc-exit")

        def snapshot(self) -> object:
            calls.append("gc-snapshot")
            return object()

    object.__setattr__(product, "epoch_runtime", SimpleNamespace(registry=Registry()))
    object.__setattr__(product, "gc_gate", GcGate())
    monkeypatch.setattr(
        preflight,
        "read_coding_product_worker_history_checkpoints_under_gc_guard",
        lambda _product: checkpoints,
    )

    def review(_product: object, **kwargs: object) -> SimpleNamespace:
        assert kwargs["attempt_id"] == "a" * 32
        calls.append("review")
        return SimpleNamespace(
            missing_proofs=("native_group_absence_unverified",),
            history_stream_snapshots=checkpoint.stream_snapshots,
            gc_reservation_revision=checkpoint.gc_reservation_revision,
            worker_backup_references=SimpleNamespace(
                owner_revision=checkpoint.backup_topology_revision
            ),
        )

    monkeypatch.setattr(
        preflight, "_review_coding_product_worker_history_under_guard", review
    )
    monkeypatch.setattr(
        preflight,
        "read_coding_worker_histories_under_gc_guard",
        lambda _product: histories,
    )
    with pytest.raises(
        preflight.CodingWorkerCutoverPreflightError,
        match="coding_worker_v2_product_closure_unproven",
    ):
        preflight.prepare_coding_product_worker_history_cutover_v2(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
    assert calls == [
        "runtime-enter",
        "gc-enter",
        "gc-snapshot",
        "review",
        "gc-exit",
        "runtime-exit",
    ]

    calls.clear()
    monkeypatch.setattr(
        preflight,
        "_review_coding_product_worker_history_under_guard",
        lambda _product, **_kwargs: SimpleNamespace(
            missing_proofs=(),
            history_stream_snapshots=checkpoint.stream_snapshots,
            gc_reservation_revision=checkpoint.gc_reservation_revision,
            worker_backup_references=SimpleNamespace(
                owner_revision=checkpoint.backup_topology_revision
            ),
        ),
    )
    prepared = preflight.prepare_coding_product_worker_history_cutover_v2(
        product, first_retained_generations=(1, 1, 1, 1, 1)
    )
    assert prepared.index.checkpoint_digest == checkpoint.record_digest
    assert calls == [
        "runtime-enter",
        "gc-enter",
        "gc-snapshot",
        "gc-exit",
        "runtime-exit",
    ]
