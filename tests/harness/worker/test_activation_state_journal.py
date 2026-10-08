from __future__ import annotations

import json
import os
import subprocess
import sys
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pytest

from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
)
from loushang.harness.worker.product_activation import _initial_state

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX Product state root")


def _race_activation_state_cas(path: Path, barrier: Any, results: Any) -> None:
    journal = WorkerActivationStateJournal(path)
    current = journal.load()
    assert current is not None
    revision = current["stateRevision"]
    assert type(revision) is int
    updated = dict(current)
    updated["stateRevision"] = revision + 1
    barrier.wait(timeout=15)
    results.put(journal.compare_and_swap(expected_revision=revision, document=updated))


def test_activation_state_cross_process_cas_has_one_winner(tmp_path: Path) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    path = root / "worker-activation-state.jsonl"
    journal = WorkerActivationStateJournal(path)
    assert journal.compare_and_swap(
        expected_revision=0, document=_initial_state(restart_budget=3)
    )
    # This test module is collected from a repository path, not installed as
    # an importable package in a fresh spawned interpreter.
    context = get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = tuple(
        context.Process(
            target=_race_activation_state_cas, args=(path, barrier, results)
        )
        for _ in range(2)
    )
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
        assert all(process.exitcode == 0 for process in processes)
        assert sorted(results.get(timeout=2) for _ in processes) == [False, True]
        latest = journal.load()
        assert latest is not None
        assert latest["stateRevision"] == 2
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def test_activation_state_reopens_across_process_and_rejects_stale_cas(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    path = root / "worker-activation-state.jsonl"
    journal = WorkerActivationStateJournal(path)
    initial = _initial_state(restart_budget=3)
    assert journal.load() is None
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    assert WorkerActivationStateJournal(path).load() == initial

    script = """
import json
import sys
from pathlib import Path
from loushang.harness.worker.activation_state_journal import WorkerActivationStateJournal

journal = WorkerActivationStateJournal(Path(sys.argv[1]))
current = journal.load()
assert current is not None
next_state = dict(current)
next_state["stateRevision"] = current["stateRevision"] + 1
assert journal.compare_and_swap(expected_revision=current["stateRevision"], document=next_state)
print(json.dumps(next_state, sort_keys=True))
"""
    child = subprocess.run(
        (sys.executable, "-c", script, str(path)),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    updated = json.loads(child.stdout)
    assert updated["stateRevision"] == 2
    assert journal.load() == updated
    assert not journal.compare_and_swap(expected_revision=0, document=initial)
    assert WorkerActivationStateJournal(path).load() == updated


def test_activation_state_read_only_refuses_orphan_and_changed_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    path = root / "worker-activation-state.jsonl"
    lock = root / "worker-activation-state.jsonl.lock"
    journal = WorkerActivationStateJournal(path)
    assert journal.load_read_only() is None
    assert tuple(root.iterdir()) == ()

    lock.touch()
    lock.chmod(0o600)
    with pytest.raises(WorkerActivationStateJournalError) as orphan:
        journal.load_read_only()
    assert orphan.value.code == "worker_activation_state_orphan_lock"
    lock.unlink()

    initial = _initial_state(restart_budget=3)
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    before = path.read_bytes()
    entries = tuple(sorted(root.iterdir()))
    assert journal.load_read_only() == initial
    assert path.read_bytes() == before
    assert tuple(sorted(root.iterdir())) == entries

    path.write_bytes(before + b'{"document":')
    damaged = path.read_bytes()
    with pytest.raises(WorkerActivationStateJournalError) as corrupt:
        journal.load_read_only()
    assert corrupt.value.code == "worker_activation_state_corrupt"
    assert path.read_bytes() == damaged


@pytest.mark.parametrize(
    "damage", ["partial_tail", "duplicate_key", "changed_revision"]
)
def test_activation_state_refuses_changed_history(tmp_path: Path, damage: str) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    path = root / "worker-activation-state.jsonl"
    journal = WorkerActivationStateJournal(path)
    assert journal.compare_and_swap(
        expected_revision=0, document=_initial_state(restart_budget=3)
    )
    original = path.read_bytes()
    if damage == "partial_tail":
        path.write_bytes(original + b'{"document":')
    elif damage == "duplicate_key":
        path.write_bytes(
            original.replace(b'{"document":', b'{"document":{},"document":', 1)
        )
    else:
        path.write_bytes(
            original.replace(b'"journalRevision":1', b'"journalRevision":2')
        )
    changed = path.read_bytes()
    with pytest.raises(WorkerActivationStateJournalError) as raised:
        journal.load()
    assert raised.value.code == "worker_activation_state_corrupt"
    assert path.read_bytes() == changed


def test_activation_state_refuses_linked_or_unprivate_authority(tmp_path: Path) -> None:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    path = root / "worker-activation-state.jsonl"
    journal = WorkerActivationStateJournal(path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"outside sentinel")
    path.symlink_to(outside)
    with pytest.raises((WorkerActivationStateJournalError, OSError, ValueError)):
        journal.load()
    assert outside.read_bytes() == b"outside sentinel"
    path.unlink()
    root.chmod(0o770)
    with pytest.raises(WorkerActivationStateJournalError) as unsafe:
        journal.compare_and_swap(
            expected_revision=0, document=_initial_state(restart_budget=3)
        )
    assert unsafe.value.code == "worker_activation_state_root_unsafe"
    assert not path.exists()
