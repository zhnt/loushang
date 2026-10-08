"""The five-stream physical proof precedes the sole V2 owner publication."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_history_commit_v2 as commit_module
from loushang.coding import (
    package_product_worker_history_preflight_v2 as preflight_module,
)
from loushang.coding.package_product_worker_history_checkpoint import (
    read_coding_product_worker_history_checkpoints_under_gc_guard,
)
from loushang.coding.package_product_worker_history_commit_v2 import (
    CodingWorkerV2OwnerCommitError,
    commit_coding_product_worker_v2_owner,
    commit_coding_worker_v2_owner_under_guard,
)
from loushang.coding.package_product_worker_history_read_v2 import (
    CodingWorkerV2ReadError,
)
from loushang.coding.package_product_worker_history_retire_v2 import (
    retire_coding_product_worker_v2_history,
)
from loushang.coding.package_product_worker_history_segments import _head_name
from loushang.coding.package_product_worker_history_stage_v2 import (
    CodingWorkerV2PreparationError,
    rollback_coding_worker_v2_preparation,
    stage_coding_product_worker_v2_preparation,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from loushang.coding.package_product_worker_history_v2_names import (
    PRODUCT_OWNER_INDEX_NAME,
)
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted


def _locks(rooted: RootedFile) -> None:
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        rooted.sibling(stem + ".jsonl.lock").create_new(b"")


def test_v2_owner_commit_proves_five_streams_and_retries_exact_owner(
    tmp_path: Path,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        assert commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared) == (
            prepared.index
        )
        assert (tmp_path / PRODUCT_OWNER_INDEX_NAME).read_bytes() == (
            prepared.index.to_bytes()
        )
        with pytest.raises(
            CodingWorkerV2PreparationError, match="owner_already_present"
        ):
            rollback_coding_worker_v2_preparation(rooted)
    with _rooted(tmp_path) as rooted:
        assert commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared) == (
            prepared.index
        )
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).atomic_write(b"{}")
    with _rooted(tmp_path) as rooted:
        with pytest.raises(CodingWorkerV2OwnerCommitError, match="owner_changed"):
            commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)


def test_v2_owner_commit_requires_existing_stream_locks(tmp_path: Path) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        with pytest.raises(CodingWorkerV2OwnerCommitError, match="lock_missing"):
            commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    assert not (tmp_path / PRODUCT_OWNER_INDEX_NAME).exists()


def test_v2_owner_commit_refuses_changed_final_stream(tmp_path: Path) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        rooted.sibling(_head_name("worker-supervisor", 1)).atomic_write(b"{}")
        with pytest.raises(CodingWorkerV2ReadError, match="active_head_changed"):
            commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    assert not (tmp_path / PRODUCT_OWNER_INDEX_NAME).exists()


def test_v2_owner_commit_interrupted_before_publication_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
        original_create = RootedFile.create_new

        def fail_owner(self: RootedFile, data: bytes) -> tuple[int, int]:
            if self._name == PRODUCT_OWNER_INDEX_NAME:
                raise OSError("injected owner publication pause")
            return original_create(self, data)

        with monkeypatch.context() as interrupted:
            interrupted.setattr(RootedFile, "create_new", fail_owner)
            with pytest.raises(OSError, match="publication pause"):
                commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
    assert not (tmp_path / PRODUCT_OWNER_INDEX_NAME).exists()
    with _rooted(tmp_path) as rooted:
        assert commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared) == (
            prepared.index
        )


def _product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> PosixLocalWheelProductSessionOwner:
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", tmp_path)
    object.__setattr__(
        product,
        "policy",
        SimpleNamespace(product_id="coding", project_scope_id="scope"),
    )

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

    class Gate:
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

    @contextmanager
    def pinned(_self: PosixLocalWheelProductSessionOwner) -> Iterator[int]:
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    object.__setattr__(product, "epoch_runtime", SimpleNamespace(registry=Registry()))
    object.__setattr__(product, "gc_gate", Gate())
    monkeypatch.setattr(
        PosixLocalWheelProductSessionOwner,
        "assert_root_gc_authority_current",
        lambda _self: None,
    )
    monkeypatch.setattr(
        PosixLocalWheelProductSessionOwner, "pinned_state_root_gc_read", pinned
    )
    return product


def test_product_v2_owner_commit_rechecks_preflight_and_retries_under_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        _locks(rooted)
    calls: list[str] = []
    product = _product(tmp_path, monkeypatch, calls)

    def preflight(_product: object, **_kwargs: object) -> object:
        assert calls == ["runtime-enter", "gc-enter", "gc-snapshot"]
        return prepared

    monkeypatch.setattr(
        commit_module,
        "_prepare_coding_product_worker_history_cutover_under_guard",
        preflight,
    )
    assert (
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
        == prepared.index
    )
    assert calls == [
        "runtime-enter",
        "gc-enter",
        "gc-snapshot",
        "gc-exit",
        "runtime-exit",
    ]
    assert (tmp_path / PRODUCT_OWNER_INDEX_NAME).read_bytes() == (
        prepared.index.to_bytes()
    )

    def no_preflight(_product: object, **_kwargs: object) -> object:
        raise AssertionError("committed V2 must not reopen pruned V1 history")

    monkeypatch.setattr(
        commit_module,
        "_prepare_coding_product_worker_history_cutover_under_guard",
        no_preflight,
    )
    assert (
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
        == prepared.index
    )


def test_product_v2_owner_commit_rejects_stale_preflight_before_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _rooted(tmp_path) as rooted:
        _write_sources(rooted)
        _locks(rooted)
    product = _product(tmp_path, monkeypatch, [])
    monkeypatch.setattr(
        commit_module,
        "_prepare_coding_product_worker_history_cutover_under_guard",
        lambda _product, **_kwargs: object(),
    )
    with pytest.raises(CodingWorkerV2OwnerCommitError, match="preparation_stale"):
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
    assert not (tmp_path / PRODUCT_OWNER_INDEX_NAME).exists()
    with pytest.raises(CodingWorkerV2OwnerCommitError, match="cutoffs_changed"):
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 2)
        )
    assert not (tmp_path / PRODUCT_OWNER_INDEX_NAME).exists()


def test_product_v2_commit_reopens_physical_checkpoint_and_five_v1_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted, stage=False)
        _locks(rooted)
    checkpoint = _sources()[0][-1]
    product = _product(tmp_path, monkeypatch, [])
    reviewed: list[str] = []

    def review(_product: object, **kwargs: object) -> SimpleNamespace:
        reviewed.append(str(kwargs["attempt_id"]))
        return SimpleNamespace(
            missing_proofs=(),
            history_stream_snapshots=checkpoint.stream_snapshots,
            gc_reservation_revision=checkpoint.gc_reservation_revision,
            worker_backup_references=SimpleNamespace(
                owner_revision=checkpoint.backup_topology_revision
            ),
        )

    monkeypatch.setattr(
        preflight_module, "_review_coding_product_worker_history_under_guard", review
    )
    staged = stage_coding_product_worker_v2_preparation(
        product, first_retained_generations=(1, 1, 1, 1, 1)
    )
    assert staged.index_digest
    assert (
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
        == prepared.index
    )
    assert reviewed == ["a" * 32] * 2
    assert (tmp_path / PRODUCT_OWNER_INDEX_NAME).read_bytes() == (
        prepared.index.to_bytes()
    )
    assert retire_coding_product_worker_v2_history(product)
    assert read_coding_product_worker_history_checkpoints_under_gc_guard(product) == (
        checkpoint,
    )
    assert (
        commit_coding_product_worker_v2_owner(
            product, first_retained_generations=(1, 1, 1, 1, 1)
        )
        == prepared.index
    )
