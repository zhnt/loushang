from __future__ import annotations

import json
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
from loushang.hosting.service import LinuxServiceIdentityV1

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle")


def _identity():
    return LinuxServiceIdentityV1(431, 100, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", os.geteuid(), 1, 1)


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


def test_child_can_settle_prebirth_abort_but_never_mint_process_exit(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.record_child_cleanup(reference, "c" * 32, _identity())
    stopped = journal.request_child_stop(reference, "c" * 32, _identity())
    assert stopped.handoff.phase is ManagedHandoffPhaseV1.ABORTING
    assert stopped.handoff.stop_requested and stopped.native_identity is None
    settled = journal.record_child_cleanup(reference, "c" * 32, _identity())
    assert settled.evidence.application_cleanup_completed
    assert not settled.evidence.process_exited and not settled.evidence.process_scope_settled
    assert journal.record_child_cleanup(reference, "c" * 32, _identity()) == settled
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.register_native(reference, "c" * 32, _identity())


def test_commit_ack_loss_is_observed_not_aborted(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    journal.register_native(reference, "c" * 32, _identity())
    committed = journal.commit(reference, "c" * 32, native_identity=_identity())
    assert committed.handoff.phase is ManagedHandoffPhaseV1.COMMITTED
    assert journal.read() == committed
    assert journal.commit(reference, "c" * 32, native_identity=_identity()) == committed
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.abort(reference, "c" * 32)
    with pytest.raises(ManagedStorageError, match="busy"):
        journal.prepare("d" * 32, expected=committed)


@pytest.mark.parametrize("first", ["stop", "abort"])
def test_stop_or_abort_before_commit_fences_child(owners, first):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    journal.register_native(reference, "c" * 32, _identity())
    if first == "stop":
        stopped = journal.request_stop(reference)
        assert journal.request_stop(reference) == stopped
    else:
        stopped = journal.abort(reference, "c" * 32)
        assert journal.abort(reference, "c" * 32) == stopped
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(reference, "c" * 32, native_identity=_identity())
    assert journal.read() == stopped


@pytest.mark.parametrize("partial", [(True, True, False), (True, False, True)])
def test_restart_requires_all_three_facts_and_old_generation_cannot_mutate_new(owners, partial):
    _, journal, _, _ = owners
    first = journal.prepare("c" * 32, expected=None)
    reference = first.handoff.instance
    journal.register_native(reference, "c" * 32, _identity())
    journal.commit(reference, "c" * 32, native_identity=_identity())
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
                 lambda: journal.commit(reference, "c" * 32, native_identity=_identity()),
                 lambda: journal.record_stop_evidence(complete.evidence)):
        with pytest.raises(ManagedStorageError, match="conflict"):
            call()
    assert journal.read() == new


def test_attempt_and_namespace_mismatch_never_commit(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    prepared = journal.register_native(prepared.handoff.instance, "c" * 32, _identity())
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(prepared.handoff.instance, "d" * 32, native_identity=_identity())
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
    prepared = journal.register_native(prepared.handoff.instance, "c" * 32, _identity())
    original_save = journal._save

    def replace_after_update(connection, state, *, insert):
        original_save(connection, state, insert=insert)
        replacement = tmp_path / "fence" / "replacement"
        replacement.write_bytes(b"")
        replacement.chmod(0o600)
        os.replace(replacement, tmp_path / "fence" / "lifecycle.lock")

    monkeypatch.setattr(journal, "_save", replace_after_update)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(prepared.handoff.instance, "c" * 32, native_identity=_identity())
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


@pytest.mark.parametrize("version", [1, 2])
def test_unactivated_old_registry_requires_explicit_upgrade_not_silent_migration(owners, tmp_path, version):
    _, _, namespace, _ = owners
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        connection.execute(f"PRAGMA user_version={version}")
    before = (tmp_path / "registry" / DATABASE_NAME).read_bytes()
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    assert (tmp_path / "registry" / DATABASE_NAME).read_bytes() == before


def test_commit_requires_exact_durable_native_registration(owners):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    with pytest.raises(ManagedContractError):
        journal.commit(reference, "c" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(reference, "c" * 32, native_identity=_identity())
    assert journal.read() == prepared
    bound = journal.register_native(reference, "c" * 32, _identity())
    assert bound.native_identity == _identity()
    assert bound.revision == prepared.revision + 1
    assert journal.register_native(reference, "c" * 32, _identity()) == bound
    wrong = replace(_identity(), start_ticks=101)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.register_native(reference, "c" * 32, wrong)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(reference, "c" * 32, native_identity=wrong)
    committed = journal.commit(reference, "c" * 32, native_identity=_identity())
    assert journal.register_native(reference, "c" * 32, _identity()) == committed


@pytest.mark.parametrize("transition", ["stop", "abort"])
def test_new_registration_cannot_cross_stop_or_abort(owners, transition):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    reference = prepared.handoff.instance
    if transition == "stop":
        stopped = journal.request_stop(reference)
    else:
        stopped = journal.abort(reference, "c" * 32)
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.register_native(reference, "c" * 32, _identity())
    assert journal.read() == stopped


def test_registration_is_bound_to_attempt_uid_and_generation(owners):
    _, journal, _, _ = owners
    first = journal.prepare("c" * 32, expected=None)
    reference = first.handoff.instance
    with pytest.raises(ManagedContractError):
        journal.register_native(reference, "c" * 32, replace(_identity(), user_id=os.geteuid() + 1))
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.register_native(reference, "d" * 32, _identity())
    journal.register_native(reference, "c" * 32, _identity())
    journal.abort(reference, "c" * 32)
    stopped = journal.record_stop_evidence(ManagedStopEvidenceV1(reference, True, True, True))
    new = journal.prepare("d" * 32, expected=stopped)
    assert new.native_identity is None
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.register_native(reference, "c" * 32, _identity())
    with pytest.raises(ManagedStorageError, match="conflict"):
        journal.commit(new.handoff.instance, "d" * 32, native_identity=_identity())
    assert journal.read() == new


def test_native_identity_survives_reopen_without_conferring_liveness(owners, tmp_path):
    registry, journal, namespace, service = owners
    prepared = journal.prepare("c" * 32, expected=None)
    bound = journal.register_native(prepared.handoff.instance, "c" * 32, _identity())
    other = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence")
    try:
        assert other.read() == bound
        assert not bound.cleanly_stopped
        assert not bound.evidence.process_exited
    finally:
        other.close()


@pytest.mark.parametrize("corruption", ["syntax", "duplicate", "type", "uid", "missing_committed"])
def test_corrupt_native_registration_is_rejected(owners, tmp_path, corruption):
    _, journal, _, _ = owners
    prepared = journal.prepare("c" * 32, expected=None)
    journal.register_native(prepared.handoff.instance, "c" * 32, _identity())
    journal.commit(prepared.handoff.instance, "c" * 32, native_identity=_identity())
    with sqlite3.connect(tmp_path / "registry" / DATABASE_NAME) as connection:
        encoded = connection.execute("SELECT native_identity FROM instances").fetchone()[0]
        if corruption == "syntax":
            broken = "{"
        elif corruption == "duplicate":
            broken = '{"pid":431,' + encoded[1:]
        elif corruption == "missing_committed":
            broken = None
        else:
            value = json.loads(encoded)
            if corruption == "type":
                value["pid"] = True
            else:
                value["user_id"] += 1
            broken = json.dumps(value, sort_keys=True, separators=(",", ":"))
        connection.execute("UPDATE instances SET native_identity=?", (broken,))
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        journal.read()
