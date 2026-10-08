"""V2 preparation is durable, resumable, and remains V1-only authority."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_history_stage_v2 as stage_module
from loushang.coding.package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from loushang.coding.package_product_worker_history_retention import (
    _known_worker_state_name,
)
from loushang.coding.package_product_worker_history_stage_v2 import (
    CodingWorkerV2PreparationError,
    CodingWorkerV2PreparationIntent,
    read_coding_worker_v2_preparation,
    rollback_coding_worker_v2_preparation,
    stage_coding_worker_v2_preparation,
)
from loushang.coding.package_product_worker_history_v2_names import (
    PREPARATION_INTENT_NAME,
    PREPARATION_STATE_NAMES,
    PRODUCT_OWNER_INDEX_NAME,
    semantic_base_name,
)
from loushang.coding.package_product_worker_posix_gc_history import (
    CodingPosixWorkerGcHistoryAuthority,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_prepared_v2 import _sources


def _prepared() -> CodingWorkerPreparedProductCutoverV2:
    checkpoints, anchor, histories = _sources()
    return CodingWorkerPreparedProductCutoverV2.from_v1_histories(
        checkpoints=checkpoints,
        anchor=anchor,
        histories=histories,
        first_retained_generations=(1, 1, 1, 1, 1),
    )


@contextmanager
def _rooted(tmp_path: Path) -> Iterator[RootedFile]:
    tmp_path.chmod(0o700)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        file_io = RootedFileIO(tmp_path, root_fd)
        try:
            with file_io.bind(
                tmp_path / PREPARATION_INTENT_NAME, durable=True
            ) as rooted:
                yield rooted
        finally:
            file_io.cleanup()
    finally:
        os.close(root_fd)


def test_v2_preparation_round_trips_and_rolls_back_exact_artifacts(
    tmp_path: Path,
) -> None:
    prepared = _prepared()
    with _rooted(tmp_path) as rooted:
        intent = stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        assert CodingWorkerV2PreparationIntent.from_bytes(intent.to_bytes()) == intent
        assert set(PREPARATION_STATE_NAMES).issubset(set(os.listdir(tmp_path)))
        assert read_coding_worker_v2_preparation(rooted) == prepared
        assert stage_coding_worker_v2_preparation(rooted, prepared=prepared) == intent
        assert rollback_coding_worker_v2_preparation(rooted)
        assert read_coding_worker_v2_preparation(rooted) is None
        assert not rollback_coding_worker_v2_preparation(rooted)
    assert not any(name in PREPARATION_STATE_NAMES for name in os.listdir(tmp_path))


def test_v2_preparation_resumes_partial_stage_and_refuses_changed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared()
    original_create = RootedFile.create_new
    interrupted = semantic_base_name("worker-opt-in")

    def fail_once(self: RootedFile, data: bytes) -> tuple[int, int]:
        if self._name == interrupted:
            raise OSError("injected preparation pause")
        return original_create(self, data)

    with _rooted(tmp_path) as rooted:
        with monkeypatch.context() as interrupted_write:
            interrupted_write.setattr(RootedFile, "create_new", fail_once)
            with pytest.raises(OSError, match="preparation pause"):
                stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        assert (tmp_path / PREPARATION_INTENT_NAME).exists()
        with pytest.raises(
            CodingWorkerV2PreparationError,
            match="coding_worker_v2_preparation_incomplete",
        ):
            read_coding_worker_v2_preparation(rooted)
        stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        changed = tmp_path / interrupted
        changed.write_bytes(changed.read_bytes() + b" ")
        with pytest.raises(
            CodingWorkerV2PreparationError,
            match="coding_worker_v2_preparation_changed",
        ):
            read_coding_worker_v2_preparation(rooted)
        with pytest.raises(
            CodingWorkerV2PreparationError,
            match="coding_worker_v2_preparation_changed",
        ):
            rollback_coding_worker_v2_preparation(rooted)


def test_v2_preparation_resumes_partial_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared()
    original_unlink = RootedFile.unlink_owned
    calls = 0

    def stop_after_one(self: RootedFile, identity: tuple[int, int]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected rollback pause")
        original_unlink(self, identity)

    with _rooted(tmp_path) as rooted:
        stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        with monkeypatch.context() as paused:
            paused.setattr(RootedFile, "unlink_owned", stop_after_one)
            with pytest.raises(OSError, match="rollback pause"):
                rollback_coding_worker_v2_preparation(rooted)
        assert (tmp_path / PREPARATION_INTENT_NAME).exists()
        assert rollback_coding_worker_v2_preparation(rooted)
        assert read_coding_worker_v2_preparation(rooted) is None


def test_v2_preparation_refuses_orphan_and_committed_owner(
    tmp_path: Path,
) -> None:
    prepared = _prepared()
    with _rooted(tmp_path) as rooted:
        orphan = rooted.sibling(semantic_base_name("worker-opt-in"))
        orphan.create_new(prepared.semantic_bases[0].to_bytes())
        with pytest.raises(
            CodingWorkerV2PreparationError,
            match="coding_worker_v2_orphan_preparation",
        ):
            stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        orphan.unlink()
        stage_coding_worker_v2_preparation(rooted, prepared=prepared)
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(b"{}")
        with pytest.raises(
            CodingWorkerV2PreparationError,
            match="coding_worker_v2_owner_already_present",
        ):
            rollback_coding_worker_v2_preparation(rooted)


def test_product_staging_and_rollback_hold_one_runtime_gc_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared()
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", tmp_path)
    object.__setattr__(product, "policy", SimpleNamespace(product_id="coding"))
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

    def prepare(
        _product: object, **_kwargs: object
    ) -> CodingWorkerPreparedProductCutoverV2:
        assert calls == ["runtime-enter", "gc-enter"]
        return prepared

    monkeypatch.setattr(
        stage_module,
        "_prepare_coding_product_worker_history_cutover_under_guard",
        prepare,
    )
    intent = stage_module.stage_coding_product_worker_v2_preparation(
        product, first_retained_generations=(1, 1, 1, 1, 1)
    )
    assert intent.index_digest
    assert calls == ["runtime-enter", "gc-enter", "gc-exit", "runtime-exit"]
    assert stage_module.rollback_coding_product_worker_v2_preparation(product)
    assert calls == [
        "runtime-enter",
        "gc-enter",
        "gc-exit",
        "runtime-exit",
        "runtime-enter",
        "gc-enter",
        "gc-exit",
        "runtime-exit",
    ]
    assert not (tmp_path / PREPARATION_INTENT_NAME).exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Product GC")
def test_product_gc_blocks_staged_v2_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared()
    with _rooted(tmp_path) as rooted:
        stage_coding_worker_v2_preparation(rooted, prepared=prepared)
    assert all(_known_worker_state_name(name) for name in PREPARATION_STATE_NAMES)
    assert _known_worker_state_name(PRODUCT_OWNER_INDEX_NAME)
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
    authority = CodingPosixWorkerGcHistoryAuthority(product)
    with pytest.raises(ValueError, match="V2 preparation remains open"):
        authority.require_settled(observed_names=tuple(os.listdir(tmp_path)))
