"""A bounded original-journal witness, not independent recovery authority."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedStopEvidenceV1
from tests.apphost.test_managed_lifecycle import _identity
from tests.apphost.test_managed_lifecycle import owners as _base_owners

owners = _base_owners
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed transitions")


def stopped(owners):
    journal = owners[1]
    state = journal.prepare("c" * 32, expected=None)
    journal.register_native(state.handoff.instance, "c" * 32, _identity())
    journal.commit(state.handoff.instance, "c" * 32, native_identity=_identity())
    journal.request_stop(state.handoff.instance)
    return journal.record_stop_evidence(ManagedStopEvidenceV1(state.handoff.instance, True, True, True))


def test_transition_retains_exact_previous_and_is_unchanged_by_current_updates(owners):
    registry, journal, _, _ = owners
    assert journal.read_transition() is None
    previous = stopped(owners)
    first = journal.read_transition()
    assert first.previous is None and first.started_revision == 1
    successor = journal.prepare("d" * 32, expected=previous)
    receipt = journal.read_transition()
    assert receipt.previous == previous
    assert receipt.instance == successor.handoff.instance
    assert receipt.attempt_id == successor.handoff.attempt_id
    assert receipt.started_revision == previous.revision + 1
    with registry._database.transaction() as connection:
        before = connection.execute("SELECT * FROM service_transitions").fetchone()
    journal.register_native(successor.handoff.instance, "d" * 32, _identity())
    journal.commit(successor.handoff.instance, "d" * 32, native_identity=_identity())
    journal.request_stop(successor.handoff.instance)
    assert journal.read_transition() == receipt
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT * FROM service_transitions").fetchone() == before
    path = registry._database._directory._root / "registry.sqlite3"
    before_file = (path.read_bytes(), path.stat().st_mtime_ns)
    assert journal.read_transition() == receipt
    assert journal.read().revision > receipt.started_revision
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before_file


@pytest.mark.parametrize("change", ["missing", "instance", "attempt", "revision", "unclean", "namespace", "service",
                                    "previous_instance", "previous_attempt", "null_previous", "noncanonical", "nested",
                                    "exit_unsettled", "scope_unsettled"])
def test_missing_mismatched_or_unclean_predecessor_is_rejected_before_journal_update(owners, change):
    registry, journal, _, _ = owners
    previous = stopped(owners)
    current = journal.prepare("d" * 32, expected=previous)
    path = registry._database._directory._root / "registry.sqlite3"
    with sqlite3.connect(path) as connection:
        if change == "missing":
            connection.execute("DELETE FROM service_transitions")
        elif change in ("instance", "attempt", "revision"):
            column, value = {"instance": ("instance_id", "e" * 32), "attempt": ("attempt_id", "e" * 32),
                             "revision": ("started_revision", previous.revision + 2)}[change]
            connection.execute(f"UPDATE service_transitions SET {column}=?", (value,))
        elif change == "null_previous":
            connection.execute("UPDATE service_transitions SET previous=NULL")
        elif change == "nested":
            connection.execute("UPDATE service_transitions SET previous=?", ("[" * 1200 + "0" + "]" * 1200,))
        else:
            raw = json.loads(connection.execute("SELECT previous FROM service_transitions").fetchone()[0])
            if change != "noncanonical":
                index, value = {"namespace": (0, "e" * 64), "service": (1, "e" * 64), "unclean": (8, 0),
                                "exit_unsettled": (7, 0), "scope_unsettled": (9, 0),
                                "previous_instance": (3, current.handoff.instance.instance_id),
                                "previous_attempt": (4, current.handoff.attempt_id)}[change]
                raw[index] = value
            encoded = json.dumps(raw) if change == "noncanonical" else json.dumps(raw, separators=(",", ":"))
            connection.execute("UPDATE service_transitions SET previous=?", (encoded,))
    before = path.read_bytes()
    for action in (journal.read, journal.read_transition,
                   lambda: journal.register_native(current.handoff.instance, "d" * 32, _identity())):
        with pytest.raises(ManagedStorageError):
            action()
    assert path.read_bytes() == before


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("table", ["instances", "service_transitions"])
def test_prepare_failure_rolls_back_both_successor_and_transition(owners, monkeypatch, table, initial):
    registry, journal, _, _ = owners
    previous = None if initial else stopped(owners)
    receipt = journal.read_transition()
    stage = ("INSERT INTO " if initial or table == "service_transitions" else "UPDATE ") + table
    original_connect = sqlite3.connect

    class Failure(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            result = super().execute(sql, parameters)
            if sql.startswith(stage):
                raise sqlite3.OperationalError("write receipt failed")
            return result

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Failure, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(ManagedStorageError):
            journal.prepare("d" * 32, expected=previous)
    assert journal.read() == previous
    assert journal.read_transition() == receipt
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM service_transitions").fetchone() == (0 if initial else 1,)


def test_prepare_lost_commit_receipt_is_resolved_by_reading_same_successor(owners, monkeypatch):
    journal = owners[1]
    previous = stopped(owners)
    original_connect = sqlite3.connect

    class Failure(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise sqlite3.OperationalError("committed without receipt")

    def connect(*args, **kwargs):
        return original_connect(*args, factory=Failure, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(ManagedStorageError):
            journal.prepare("d" * 32, expected=previous, deadline=monotonic() + 5)
    current = journal.read()
    receipt = journal.read_transition()
    assert current.handoff.attempt_id == "d" * 32
    assert receipt.instance == current.handoff.instance and receipt.previous == previous
    with pytest.raises(ManagedStorageError):
        journal.prepare("d" * 32, expected=previous)
    assert journal.read_transition() == receipt


def test_clean_failed_generation_without_native_can_precede_another_generation(owners):
    registry, journal, _, _ = owners
    first = stopped(owners)
    second = journal.prepare("d" * 32, expected=first)
    journal.request_stop(second.handoff.instance)
    second = journal.record_stop_evidence(ManagedStopEvidenceV1(second.handoff.instance, True, True, True))
    assert second.native_identity is None
    assert journal.read_transition().previous == first
    third = journal.prepare("e" * 32, expected=second)
    receipt = journal.read_transition()
    assert receipt.previous == second and receipt.previous != first
    assert receipt.instance == third.handoff.instance
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM service_transitions").fetchone() == (1,)


def test_deferred_foreign_key_rejects_one_sided_successor_change_at_commit(owners):
    registry, journal, _, _ = owners
    state = journal.prepare("c" * 32, expected=None)
    receipt = journal.read_transition()
    path = registry._database._directory._root / "registry.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE instances SET instance_id=?", ("e" * 32,))
        # A statement can succeed while its deferred constraint remains owed.
        with pytest.raises(sqlite3.IntegrityError):
            connection.commit()
        connection.rollback()
    assert journal.read() == state and journal.read_transition() == receipt


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("table", ["instances", "service_transitions"])
def test_real_exit_between_prepare_writes_keeps_original_pair(owners, initial, table):
    from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
    from loushang.apphost.managed.registry import ManagedRegistryV1

    registry, journal, namespace, service = owners
    previous = None if initial else stopped(owners)
    receipt = journal.read_transition()
    root, fence = registry._database._directory._root, journal._fence._root
    stage = ("INSERT INTO " if initial or table == "service_transitions" else "UPDATE ") + table
    script = """
import os, sqlite3, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
root, fence, platform, stage = sys.argv[1:]
namespace = ManagedNamespaceV1(platform, os.geteuid(), 'a'*32)
key = ManagedServiceKeyV1('coding', '/workspace')
registry = ManagedRegistryV1(Path(root), namespace)
journal = ManagedServiceJournalV1(registry, namespace, key, Path(fence))
expected = journal.read()
original = sqlite3.connect
class Crash(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if sql.startswith(stage):
            os._exit(23)
        return result
def connect(*args, **kwargs):
    return original(*args, factory=Crash, **kwargs)
sqlite3.connect = connect
journal.prepare('d'*32, expected=expected)
os._exit(24)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    process = subprocess.run([sys.executable, "-c", script, str(root), str(fence), namespace.platform_home, stage],
                             env=env, capture_output=True, timeout=10)
    assert process.returncode == 23, process.stderr
    journal.close()
    registry.close()
    recovered = ManagedRegistryV1(root, namespace, create=True)
    reopened = ManagedServiceJournalV1(recovered, namespace, service, fence)
    try:
        assert reopened.read() == previous and reopened.read_transition() == receipt
    finally:
        reopened.close()
        recovered.close()
