from __future__ import annotations

import json
from time import monotonic

import pytest

from loushang.apphost.managed import _files
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedStopEvidenceV1

from .test_managed_lifecycle import _identity
from .test_managed_lifecycle import owners as owners
from .test_managed_lifecycle import pytestmark as pytestmark


def started(journal):
    first = journal.prepare("c" * 32, expected=None)
    journal.register_native(first.handoff.instance, "c" * 32, _identity())
    return first.handoff.instance


def publish(journal, instance, deadline_ms):
    return journal.record_trace_application(instance, "c" * 32,
        native_identity=_identity(), trace_deadline_ms=deadline_ms)


def test_trace_fact_is_idempotent_preserved_and_not_inherited_by_successor(owners):
    _, journal, _, _ = owners
    instance = started(journal)
    deadline = int((monotonic() + 60) * 1000)
    applied = publish(journal, instance, deadline)
    assert applied.trace_application.deadline_ms == deadline
    assert publish(journal, instance, deadline) == applied
    with pytest.raises(ManagedStorageError, match="conflict"):
        publish(journal, instance, deadline + 1)
    committed = journal.commit(instance, "c" * 32, native_identity=_identity())
    assert committed.trace_application == applied.trace_application
    journal.request_stop(instance)
    complete = journal.record_stop_evidence(ManagedStopEvidenceV1(instance, True, True, True))
    assert publish(journal, instance, deadline) == complete
    fresh = journal.prepare("d" * 32, expected=complete)
    assert fresh.trace_application is None
    assert journal.read_transition().previous.trace_application == applied.trace_application
    with pytest.raises(ManagedStorageError, match="conflict"):
        publish(journal, instance, deadline)


def test_trace_receipt_cannot_consume_control_headroom(owners, monkeypatch):
    registry, journal, _, _ = owners
    instance = started(journal)
    def full(connection):
        raise ManagedStorageError("capacity")
    monkeypatch.setattr(registry._database, "admit_growth", full)
    with pytest.raises(ManagedStorageError, match="capacity"):
        publish(journal, instance, int((monotonic() + 60) * 1000))
    assert journal.read().trace_application is None
    assert journal.request_stop(instance).handoff.stop_requested


@pytest.mark.parametrize("phase", ["growth", "save"])
def test_expiry_during_first_publication_rolls_back_fact_and_revision(owners, monkeypatch, phase):
    registry, journal, _, _ = owners
    instance = started(journal)
    before = journal.read()
    now = [monotonic()]
    deadline = int((now[0] + 60) * 1000)
    monkeypatch.setattr(_files, "monotonic", lambda: now[0])
    target, name = (registry._database, "admit_growth") if phase == "growth" else (journal, "_save")
    original = getattr(target, name)
    def expires(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] = deadline / 1000 + 1
        return result
    with monkeypatch.context() as patch:
        patch.setattr(target, name, expires)
        with pytest.raises(ManagedStorageError, match="busy"):
            publish(journal, instance, deadline)
    assert journal.read() == before


def test_same_trace_fact_can_be_reobserved_after_expiry(owners, monkeypatch):
    _, journal, _, _ = owners
    instance = started(journal)
    deadline = int((monotonic() + 60) * 1000)
    applied = publish(journal, instance, deadline)
    monkeypatch.setattr(_files, "monotonic", lambda: deadline / 1000 + 1)
    assert publish(journal, instance, deadline) == applied


@pytest.mark.parametrize("reason", ["stopped", "expired", "wrong_attempt", "unbound"])
def test_trace_cannot_first_publish_without_current_eligible_binding(owners, reason):
    _, journal, _, _ = owners
    if reason == "unbound":
        instance = journal.prepare("c" * 32, expected=None).handoff.instance
    else:
        instance = started(journal)
    if reason == "stopped":
        journal.request_stop(instance)
    deadline = 1 if reason == "expired" else int((monotonic() + 60) * 1000)
    before = journal.read()
    with pytest.raises(ManagedStorageError):
        journal.record_trace_application(instance, "d" * 32 if reason == "wrong_attempt" else "c" * 32,
            native_identity=_identity(), trace_deadline_ms=deadline)
    assert journal.read() == before


@pytest.mark.parametrize("damage", ["instance_id", "attempt_id", "configuration", "v"])
def test_corrupt_trace_fact_is_rejected_by_state_decoder(owners, damage):
    registry, journal, _, _ = owners
    instance = started(journal)
    publish(journal, instance, int((monotonic() + 60) * 1000))
    with registry._database.transaction(write=True) as connection:
        row = json.loads(connection.execute("SELECT trace_application FROM instances").fetchone()[0])
        row[damage] = 2 if damage == "v" else "f" * 32
        connection.execute("UPDATE instances SET trace_application=?", (json.dumps(row, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        journal.read()
