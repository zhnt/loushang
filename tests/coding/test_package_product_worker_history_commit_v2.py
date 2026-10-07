"""The five-stream physical proof precedes the sole V2 owner publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.package_product_worker_history_commit_v2 import (
    CodingWorkerV2OwnerCommitError,
    commit_coding_worker_v2_owner_under_guard,
)
from loushang.coding.package_product_worker_history_read_v2 import (
    CodingWorkerV2ReadError,
)
from loushang.coding.package_product_worker_history_segments import _head_name
from loushang.coding.package_product_worker_history_stage_v2 import (
    CodingWorkerV2PreparationError,
    rollback_coding_worker_v2_preparation,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from loushang.coding.package_product_worker_history_v2_names import (
    PRODUCT_OWNER_INDEX_NAME,
)
from loushang.harness.journal._rooted_io import RootedFile
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
