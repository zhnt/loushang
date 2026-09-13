from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.apphost.managed._database import DATABASE_NAME
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
)
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle")


@pytest.fixture
def owners(tmp_path):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", "/workspace")
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    journal = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence", create=True)
    try:
        yield registry, journal, namespace, service
    finally:
        journal.close()
        registry.close()


def test_prepare_is_durable_and_never_repeated_as_another_spawn(owners, tmp_path):
    registry, journal, namespace, service = owners
    assert journal.read() is None
    prepared = journal.prepare("c" * 32, expected=None)
    assert prepared.revision == 1
    assert prepared.handoff.phase is ManagedHandoffPhaseV1.PROVISIONAL
    journal.close()
    other = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence")
    try:
        assert other.read() == prepared
        with pytest.raises(ManagedStorageError, match="conflict"):
            other.prepare("c" * 32, expected=None)
        with pytest.raises(ManagedStorageError, match="busy"):
            other.prepare("d" * 32, expected=prepared)
    finally:
        other.close()


def test_commit_ack_loss_is_observed_not_aborted(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    committed = journal.commit(reference, "c" * 32)
    assert committed.handoff.phase is ManagedHandoffPhaseV1.COMMITTED
    assert journal.read() == committed
    assert journal.commit(reference, "c" * 32) == committed
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.abort(reference, "c" * 32)
    with pytest.raises(ManagedStorageError, match="busy"):
        journal.prepare("d" * 32, expected=committed)


@pytest.mark.parametrize("first", ["stop", "abort"])
def test_stop_or_abort_before_commit_fences_child(owners, first):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    if first == "stop":
        stopped = journal.request_stop(reference)
        assert journal.request_stop(reference) == stopped
    else:
        stopped = journal.abort(reference, "c" * 32)
        assert journal.abort(reference, "c" * 32) == stopped
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(reference, "c" * 32)
    assert journal.read() == stopped


@pytest.mark.parametrize("partial", [(True, True, False), (True, False, True)])
def test_restart_requires_all_three_facts_and_old_generation_cannot_mutate_new(owners, partial):
    _, journal, _, _ = owners
    first = journal.prepare("c" * 32, expected=None)
    reference = first.handoff.instance
    journal.commit(reference, "c" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.record_stop_evidence(ManagedStopEvidenceV1(reference, True, True, True))
    journal.request_stop(reference)
    incomplete = journal.record_stop_evidence(ManagedStopEvidenceV1(reference, *partial))
    assert not incomplete.cleanly_stopped
    with pytest.raises(ManagedStorageError, match="busy"):
        journal.prepare("d" * 32, expected=incomplete)
    complete = journal.record_stop_evidence(ManagedStopEvidenceV1(reference, *(not item for item in partial)))
    assert complete.cleanly_stopped
    assert journal.record_stop_evidence(ManagedStopEvidenceV1(reference, False, False, False)) == complete
    new = journal.prepare("d" * 32, expected=complete)
    assert new.revision > complete.revision
    assert new.handoff.instance != reference
    for call in (lambda: journal.request_stop(reference),
                 lambda: journal.abort(reference, "c" * 32),
                 lambda: journal.commit(reference, "c" * 32),
                 lambda: journal.record_stop_evidence(complete.evidence)):
        with pytest.raises(ManagedStorageError, match="conflict"):
            call()
    assert journal.read() == new


def test_attempt_and_namespace_mismatch_never_commit(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(prepared.handoff.instance, "d" * 32)
    with pytest.raises(ManagedContractError):
        journal.request_stop(replace(prepared.handoff.instance, namespace_key="a" * 64))
    assert journal.read() == prepared


def test_control_headroom_remains_when_normal_admission_is_closed(owners, monkeypatch):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    monkeypatch.setattr(os, "fstatvfs", lambda fd: SimpleNamespace(f_bavail=2560, f_frsize=4096))
    stopped = journal.request_stop(prepared.handoff.instance)
    assert stopped.handoff.stop_requested
    complete = journal.record_stop_evidence(ManagedStopEvidenceV1(prepared.handoff.instance, True, True, True))
    with pytest.raises(ManagedStorageError, match="capacity"):
        journal.prepare("d" * 32, expected=complete)
    assert journal.read() == complete


def test_corrupt_boolean_observation_is_not_accepted(owners, tmp_path):
    _, journal, _, _ = owners
    journal.prepare("c" * 32, expected=None)
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        connection.execute("UPDATE instances SET stop_requested=2")
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        journal.read()


def test_replaced_service_fence_rolls_back_before_database_commit(owners, tmp_path, monkeypatch):
    registry, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    original_save = journal._save

    def replace_after_update(connection, state, *, insert):
        original_save(connection, state, insert=insert)
        replacement = tmp_path / "fence" / "replacement"
        replacement.write_bytes(b"")
        replacement.chmod(0o600)
        os.replace(replacement, tmp_path / "fence" / "lifecycle.lock")

    monkeypatch.setattr(journal, "_save", replace_after_update)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(prepared.handoff.instance, "c" * 32)
    with registry._database.transaction() as connection:
        assert connection.execute("SELECT phase FROM instances").fetchone() == ("provisional",)


def test_real_competing_process_only_one_generation_is_reserved(owners, tmp_path):
    _, journal, namespace, _ = owners
    script = """
import os, sys
from pathlib import Path
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed._files import ManagedStorageError
namespace = ManagedNamespaceV1(sys.argv[2], os.geteuid(), 'a'*32)
registry = ManagedRegistryV1(Path(sys.argv[1])/'registry', namespace)
journal = ManagedServiceJournalV1(registry, namespace, ManagedServiceKeyV1('coding', '/workspace'), Path(sys.argv[1])/'fence')
try:
    journal.prepare('d'*32, expected=None)
    print('reserved')
except ManagedStorageError as error:
    print(error.code)
finally:
    journal.close()
    registry.close()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    with journal._fence.lock("lifecycle.lock"):
        busy = subprocess.run([sys.executable, "-c", script, str(tmp_path), namespace.platform_home],
                              env=env, capture_output=True, text=True, timeout=10)
        assert busy.returncode == 0, busy.stderr
        assert busy.stdout.strip() == "busy"
    prepared = journal.prepare("c" * 32, expected=None)
    conflict = subprocess.run([sys.executable, "-c", script, str(tmp_path), namespace.platform_home],
                              env=env, capture_output=True, text=True, timeout=10)
    assert conflict.returncode == 0, conflict.stderr
    assert conflict.stdout.strip() == "conflict"
    assert journal.read() == prepared


def test_unactivated_v1_registry_requires_explicit_upgrade_not_silent_migration(owners, tmp_path):
    _, _, namespace, _ = owners
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        connection.execute("PRAGMA user_version=1")
    before = (tmp_path / "registry" / DATABASE_NAME).read_bytes()
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    assert (tmp_path / "registry" / DATABASE_NAME).read_bytes() == before
