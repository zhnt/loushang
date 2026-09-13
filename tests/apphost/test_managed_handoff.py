from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from secrets import token_hex
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedHandoffPhaseV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
)
from loushang.apphost.managed.handoff import ManagedServiceHandoffPortV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.hosting.service import LinuxServiceObserverV1
from loushang.hosting.service_handoff import (
    ServiceChildHandoffV1,
    ServiceParentHandoffV1,
)
from loushang.hosting.service_handoff import ServiceHandoffPhaseV1 as Phase

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux durable handoff")


@pytest.fixture
def owners(tmp_path):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid(), "a" * 32)
    service = ManagedServiceKeyV1("coding", "/workspace")
    registry = ManagedRegistryV1(tmp_path / "registry", namespace, create=True)
    registry.reserve_mux(ManagedMuxReservationV1("dev", service, "b" * 32))
    journal = ManagedServiceJournalV1(registry, namespace, service, tmp_path / "fence", create=True)
    state = journal.prepare("c" * 32, expected=None)
    port = ManagedServiceHandoffPortV1(journal, state.handoff.instance, state.handoff.attempt_id)
    try:
        yield journal, state, port
    finally:
        journal.close()
        registry.close()


def test_port_observes_durable_commit_and_refuses_abort(owners):
    _, _, port = owners
    assert port.observe() is Phase.PROVISIONAL
    assert port.commit() is Phase.COMMITTED
    assert port.abort() is Phase.COMMITTED


def test_uncertain_commit_reobserves_without_replaying_mutation(owners, monkeypatch):
    journal, _, port = owners
    original = journal.commit
    calls = 0

    def commit_then_error(*args, **kwargs):
        nonlocal calls
        calls += 1
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(journal, "commit", commit_then_error)
    assert port.commit() is Phase.COMMITTED
    assert calls == 1


def test_unavailable_journal_is_unknown_not_authority(owners, monkeypatch):
    journal, _, port = owners

    def fail(*args, **kwargs):
        raise ManagedStorageError("busy")

    monkeypatch.setattr(journal, "read", fail)
    monkeypatch.setattr(journal, "commit", fail)
    monkeypatch.setattr(journal, "abort", fail)
    assert port.observe() is Phase.UNKNOWN
    assert port.commit() is Phase.UNKNOWN
    assert port.abort() is Phase.UNKNOWN


def test_stop_fence_is_not_a_fabricated_abort(owners):
    journal, state, port = owners
    journal.request_stop(state.handoff.instance)
    assert port.commit() is Phase.PROVISIONAL
    assert port.abort() is Phase.ABORTING


@pytest.mark.parametrize("mismatch", ["namespace", "instance", "attempt"])
def test_binding_mismatch_cannot_observe_or_modify_current_attempt(owners, mismatch):
    journal, state, _ = owners
    reference, attempt = state.handoff.instance, state.handoff.attempt_id
    if mismatch == "namespace":
        reference = replace(reference, namespace_key="d" * 64)
    elif mismatch == "instance":
        reference = replace(reference, instance_id="d" * 32)
    else:
        attempt = "d" * 32
    port = ManagedServiceHandoffPortV1(journal, reference, attempt)
    assert port.observe() is Phase.UNKNOWN
    assert port.commit() is Phase.UNKNOWN
    assert port.abort() is Phase.UNKNOWN
    assert journal.read() == state


def test_delayed_old_port_never_controls_new_generation(owners):
    journal, state, port = owners
    assert port.abort() is Phase.ABORTING
    stopped = journal.record_stop_evidence(ManagedStopEvidenceV1(state.handoff.instance, True, True, True))
    new = journal.prepare("d" * 32, expected=stopped)
    assert port.observe() is Phase.UNKNOWN
    assert port.commit() is Phase.UNKNOWN
    assert port.abort() is Phase.UNKNOWN
    assert journal.read() == new


@pytest.mark.parametrize("abort_wins", [False, True])
def test_eof_racing_after_alive_peek_is_decided_by_durable_cas(owners, monkeypatch, abort_wins):
    journal, _, port = owners
    left, right = socket.socketpair()
    parent, child = ServiceParentHandoffV1(left, port), ServiceChildHandoffV1(right, port)
    original = child._parent_lost

    def close_after_alive_peek():
        assert original() is False
        parent.close()
        if abort_wins:
            assert port.abort() is Phase.ABORTING
        return False

    monkeypatch.setattr(child, "_parent_lost", close_after_alive_peek)
    try:
        expected = Phase.ABORTING if abort_wins else Phase.COMMITTED
        assert child.commit() is expected
        assert child.poll_parent() is expected
        assert port.abort() is expected
        assert journal.read().handoff.phase.value == expected.value
    finally:
        parent.close()
        child.close()


@pytest.mark.parametrize("owner", ["fence", "database"])
def test_port_deadline_includes_both_native_owner_mutexes(owners, owner):
    journal, _, port = owners
    mutex = journal._fence._mutex if owner == "fence" else journal._database._directory._mutex
    locked, release = threading.Event(), threading.Event()

    def hold():
        with mutex:
            locked.set()
            assert release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert locked.wait(5)
        started = monotonic()
        assert port.observe(started + 0.05) is Phase.UNKNOWN
        assert monotonic() - started < 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert port.observe() is Phase.PROVISIONAL


def test_expired_transaction_rolls_back_without_fresh_reobservation_budget(owners, monkeypatch):
    import loushang.apphost.managed._database as database
    import loushang.apphost.managed._files as files

    journal, state, port = owners
    now = [10.0]
    monkeypatch.setattr(files, "monotonic", lambda: now[0])
    monkeypatch.setattr(database, "monotonic", lambda: now[0])
    original = journal._save
    saved = []

    def save_then_expire(*args, **kwargs):
        original(*args, **kwargs)
        saved.append(True)
        now[0] = 11.0

    monkeypatch.setattr(journal, "_save", save_then_expire)
    assert port.commit(10.5) is Phase.UNKNOWN
    assert saved == [True]
    assert journal.read() == state


def test_sql_progress_uses_callers_deadline_not_a_fresh_two_seconds(owners, monkeypatch):
    import loushang.apphost.managed._database as database
    import loushang.apphost.managed._files as files

    journal, _, port = owners
    now = [10.0]
    monkeypatch.setattr(files, "monotonic", lambda: now[0])
    monkeypatch.setattr(database, "monotonic", lambda: now[0])

    def long_query(connection):
        now[0] = 11.0  # Caller budget is spent, the local two seconds are not.
        connection.execute("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 "
                           "FROM n WHERE x<10000) SELECT sum(x) FROM n").fetchone()
        pytest.fail("expired SQL must be interrupted")

    monkeypatch.setattr(journal._database, "_validate_schema", long_query)
    assert port.observe(10.5) is Phase.UNKNOWN


_CHILD = r'''
import os, socket, sys
from pathlib import Path
from loushang.apphost.managed.contracts import ManagedNamespaceV1, ManagedServiceKeyV1
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.handoff import ManagedServiceHandoffPortV1
from loushang.hosting.service_handoff import ServiceChildHandoffV1
root = Path(sys.argv[1])
control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
control.settimeout(8)
control.connect('\0' + sys.argv[2])
endpoint = socket.socket(fileno=int(sys.argv[3]))
namespace = ManagedNamespaceV1(str(root / 'platform'), os.geteuid(), 'a' * 32)
registry = ManagedRegistryV1(root / 'registry', namespace)
journal = ManagedServiceJournalV1(registry, namespace, ManagedServiceKeyV1('coding', '/workspace'), root / 'fence')
state = journal.read()
port = ManagedServiceHandoffPortV1(journal, state.handoff.instance, state.handoff.attempt_id)
channel = ServiceChildHandoffV1(endpoint, port)
try:
    control.sendall(b'R')
    while True:
        command = control.recv(1)
        if not command or command == b'Q':
            break
        phase = channel.commit() if command == b'C' else channel.poll_parent()
        control.sendall(phase.value.encode() + b'\n')
finally:
    channel.close()
    journal.close()
    registry.close()
    control.close()
'''

_STARTER = r'''
import json, os, socket, sys
from loushang.hosting.contracts import ProcessLaunchRequest, ProcessStreamSpec, ProcessStdinMode, ProcessStdoutMode, ProcessStderrMode
from loushang.hosting.service_process import LinuxServiceProcessV1
parent, child = socket.socketpair()
command = json.loads(sys.argv[1]) + [str(child.fileno())]
request = ProcessLaunchRequest(tuple(command), sys.argv[2], tuple(os.environ.items()),
    ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD))
owner = LinuxServiceProcessV1(request, child)
identity = owner.spawn()
print(identity.pid, flush=True)
sys.stdin.buffer.read(1)
if sys.argv[3] == 'abrupt':
    os._exit(0)
owner.close()
parent.close()
'''


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("exit_mode", ["normal", "abrupt"])
def test_real_starter_exit_obeys_durable_handoff(owners, tmp_path, committed, exit_mode):
    journal, _, port = owners
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    address = "lmux-handoff-test-" + token_hex(16)
    listener.bind("\0" + address)
    listener.listen(1)
    listener.settimeout(8)
    control = None
    command = [sys.executable, "-c", _CHILD, str(tmp_path), address]
    starter = subprocess.Popen(
        [sys.executable, "-c", _STARTER, json.dumps(command), str(tmp_path), exit_mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    observer = None
    try:
        assert starter.stdout is not None
        poller = select.poll()
        poller.register(starter.stdout, select.POLLIN)
        assert poller.poll(5000), "starter failed to report child"
        observer = LinuxServiceObserverV1.capture(int(starter.stdout.readline()))
        control, _ = listener.accept()
        control.settimeout(8)
        assert control.recv(1) == b"R"
        if committed:
            control.sendall(b"C")
            assert _line(control) == b"committed\n"
        _, errors = starter.communicate(b"Q", timeout=5)
        assert starter.returncode == 0, errors.decode(errors="replace")
        assert not observer.exited()
        control.sendall(b"P")
        expected = Phase.COMMITTED if committed else Phase.ABORTING
        assert _line(control) == expected.value.encode() + b"\n"
        assert port.observe() is expected
        assert journal.read().handoff.phase is ManagedHandoffPhaseV1(expected.value)
        # The handshake does not fabricate application/scope cleanup facts, nor
        # stop the committed child. The test application owns its separate exit.
        assert not journal.read().evidence.application_cleanup_completed
        assert not journal.read().evidence.process_scope_settled
        assert not observer.exited()
    finally:
        listener.close()
        if control is not None:
            control.close()  # EOF is the test child's own exit protocol, no signals.
        starter.communicate(timeout=5)
        if observer is not None:
            try:
                assert observer.exited(timeout=8)
            finally:
                observer.close()


def _line(endpoint):
    result = bytearray()
    while len(result) < 32:
        value = endpoint.recv(1)
        if not value:
            break
        result.extend(value)
        if value == b"\n":
            break
    return bytes(result)
