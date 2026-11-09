"""The shared translation keeps the caller's argument-evaluation failure region."""

from contextlib import contextmanager

import pytest

from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointError,
)
from loushang.coding.package_product_worker_history_read_v2 import _HISTORY_READER
from loushang.harness.worker.history._rooted_supervisor import RootedSupervisorJournal
from loushang.harness.worker.journal import WorkerSupervisorJournalError


def test_checkpoint_scope_failure_keeps_original_code_and_cause(tmp_path):
    original = CodingWorkerHistoryCheckpointError("scope_read_failed")

    class Access:
        @property
        def scope_id(self):
            raise original

        @property
        def store_id(self):
            raise AssertionError("store must not be read after the scope failure")

        @contextmanager
        def guard(self, *, require_write):
            raise AssertionError("the private fence must not acquire authority")
            yield

        def assert_current(self):
            raise AssertionError("the private fence must not create a new check")

    journal = RootedSupervisorJournal(
        tmp_path / "worker-supervisor.jsonl",
        access=Access(),
        history_reader=_HISTORY_READER,
    )
    # Scope fails before the raw reader can access any rooted file.
    with pytest.raises(WorkerSupervisorJournalError) as failure:
        journal._checkpoint_writer_fence(object())
    assert failure.value.code == original.code
    assert failure.value.__cause__ is original
    assert failure.value.__suppress_context__
    assert list(tmp_path.iterdir()) == []
