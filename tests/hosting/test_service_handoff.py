from __future__ import annotations

import os
import socket
import sys
import threading

import pytest

from loushang.hosting.errors import HostingError, HostingFailureCategory
from loushang.hosting.service_handoff import (
    ServiceChildHandoffV1,
    ServiceParentHandoffV1,
)
from loushang.hosting.service_handoff import (
    ServiceHandoffPhaseV1 as Phase,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux inherited handoff")


class Port:
    def __init__(self):
        self.phase = Phase.PROVISIONAL
        self.failure = False

    def observe(self, deadline=None):
        if self.failure:
            raise OSError("unavailable")
        return self.phase

    def commit(self, deadline=None):
        if self.phase is Phase.PROVISIONAL:
            self.phase = Phase.COMMITTED
        return self.observe()

    def abort(self, deadline=None):
        if self.phase is Phase.PROVISIONAL:
            self.phase = Phase.ABORTING
        return self.observe()


@pytest.fixture
def channels():
    left, right = socket.socketpair()
    port = Port()
    parent, child = ServiceParentHandoffV1(left, port), ServiceChildHandoffV1(right, port)
    try:
        yield parent, child, port
    finally:
        parent.close()
        child.close()


def test_timeout_never_aborts_or_commits(channels):
    parent, child, port = channels
    assert parent.wait(timeout=0) is Phase.UNKNOWN
    assert port.phase is Phase.PROVISIONAL
    assert child.poll_parent() is Phase.PROVISIONAL


@pytest.mark.parametrize("action", ["poll_parent", "commit"])
def test_child_respects_absolute_deadline_despite_delayed_entry(channels, monkeypatch, action):
    import loushang.hosting.service_handoff as module

    _, child, port = channels
    recorded = []
    monkeypatch.setattr(module, "monotonic", lambda: 11.0)

    def observe(deadline):
        recorded.append(deadline)
        return Phase.PROVISIONAL

    monkeypatch.setattr(port, "observe", observe)
    if action == "commit":
        monkeypatch.setattr(port, "commit", lambda deadline: recorded.append(deadline) or Phase.COMMITTED)
    # The caller computed a two-second relative budget earlier, at t=10.
    getattr(child, action)(timeout=2, deadline=12)
    assert recorded and set(recorded) == {12}
    recorded.clear()
    assert getattr(child, action)(timeout=2, deadline=10) is Phase.UNKNOWN
    assert recorded == []


def test_commit_survives_parent_close_and_late_abort(channels):
    parent, child, port = channels
    assert child.commit() is Phase.COMMITTED
    assert parent.wait(timeout=1) is Phase.COMMITTED
    assert parent.abort() is Phase.COMMITTED
    parent.close()
    assert child.poll_parent() is Phase.COMMITTED
    assert child.commit() is Phase.COMMITTED
    assert port.phase is Phase.COMMITTED


def test_parent_eof_before_readiness_requires_durable_abort(channels):
    parent, child, port = channels
    parent.close()
    assert child.commit() is Phase.ABORTING
    assert port.phase is Phase.ABORTING


def test_unknown_storage_after_parent_loss_is_not_cleanup_authority(channels):
    parent, child, port = channels
    port.failure = True
    parent.close()
    assert child.poll_parent() is Phase.UNKNOWN
    assert port.phase is Phase.PROVISIONAL
    port.failure = False
    assert child.poll_parent() is Phase.ABORTING


def test_wire_byte_is_not_commit_proof(channels):
    parent, child, port = channels
    child._endpoint.send(b"C")
    assert parent.wait(timeout=0.1) is Phase.UNKNOWN
    assert port.phase is Phase.PROVISIONAL


def test_unexpected_parent_data_aborts_via_port(channels):
    parent, child, port = channels
    parent._endpoint.send(b"C")
    assert child.poll_parent() is Phase.ABORTING
    assert port.phase is Phase.ABORTING


def test_ack_loss_after_durable_commit_never_undoes_state(channels, monkeypatch):
    parent, child, port = channels
    original = port.commit

    def commit_and_disconnect(deadline):
        result = original()
        parent.close()
        return result

    monkeypatch.setattr(port, "commit", commit_and_disconnect)
    assert child.commit() is Phase.COMMITTED
    assert child.poll_parent() is Phase.COMMITTED


def test_exception_after_commit_is_unknown_until_reobserved(channels, monkeypatch):
    parent, child, port = channels

    def commit_then_error(deadline):
        port.phase = Phase.COMMITTED
        raise OSError("reply lost")

    monkeypatch.setattr(port, "commit", commit_then_error)
    assert child.commit() is Phase.UNKNOWN
    parent.close()
    assert child.poll_parent() is Phase.COMMITTED


@pytest.mark.parametrize("timeout", [True, -1, 31, float("nan"), float("inf"), 10**1000, "1"])
def test_invalid_timeouts_are_bounded_errors(channels, timeout):
    with pytest.raises(HostingError) as caught:
        channels[0].wait(timeout=timeout)
    assert caught.value.category is HostingFailureCategory.INVALID_REQUEST


def test_adopted_channels_do_not_leak_to_exec(channels):
    parent, child, _ = channels
    for owner in (parent, child):
        assert not owner._endpoint.getblocking()
        assert not os.get_inheritable(owner._endpoint.fileno())


@pytest.mark.parametrize("channel_type", [ServiceParentHandoffV1, ServiceChildHandoffV1])
def test_native_close_uncertainty_never_retries_reused_descriptor(tmp_path, monkeypatch, channel_type):
    peer, endpoint = socket.socketpair()
    owner = channel_type(endpoint, Port())
    original = socket.socket._real_close
    calls, replacements = [], []

    def fail_after_release(self):
        original(self)
        if self is endpoint:
            calls.append(1)
            replacements.append(os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
            raise OSError("uncertain native socket close")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "_real_close", fail_after_release)
            for _ in range(2):
                with pytest.raises(HostingError) as caught:
                    owner.close()
                assert caught.value.category is HostingFailureCategory.CLEANUP_FAILED
        assert calls == [1] and not owner._closed and endpoint.fileno() == -1
        os.fstat(replacements[0])
    finally:
        peer.close()
        for fd in replacements:
            os.close(fd)


def test_close_mutex_failure_can_retry_before_native_close(channels, monkeypatch):
    owner = channels[0]
    original = owner._mutex

    class Denied:
        def acquire(self, **kwargs):
            return False

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_mutex", Denied())
        with pytest.raises(HostingError):
            owner.close()
        assert not owner._close_started and owner._endpoint.fileno() >= 0
    assert owner._mutex is original
    owner.close()
    assert owner._closed


def test_failed_admission_leaves_socket_with_caller():
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        with pytest.raises(HostingError):
            ServiceParentHandoffV1(endpoint, Port())
        assert endpoint.fileno() >= 0
    finally:
        endpoint.close()


def test_closed_channel_rejects_new_calls(channels):
    parent, child, _ = channels
    parent.close()
    child.close()
    for operation in (lambda: parent.wait(timeout=0), parent.abort, child.commit, child.poll_parent):
        with pytest.raises(HostingError) as caught:
            operation()
        assert caught.value.category is HostingFailureCategory.HOST_CLOSED


def test_contended_wait_spends_no_extra_lock_budget(channels):
    parent, _, _ = channels
    locked, release = threading.Event(), threading.Event()

    def hold():
        with parent._mutex:
            locked.set()
            assert release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert locked.wait(5)
        with pytest.raises(HostingError) as caught:
            parent.wait(timeout=0)
        assert caught.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()


def test_invalid_port_value_never_becomes_authority(channels):
    parent, child, port = channels
    port.phase = "committed"
    assert parent.wait(timeout=0) is Phase.UNKNOWN
    assert child.commit() is Phase.UNKNOWN


def test_budget_exhaustion_does_not_start_second_observation(channels, monkeypatch):
    import loushang.hosting.service_handoff as module

    parent, _, port = channels
    now = [10.0]
    deadlines = []
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    def observe(deadline):
        deadlines.append(deadline)
        now[0] = deadline
        return Phase.PROVISIONAL

    monkeypatch.setattr(port, "observe", observe)
    assert parent.wait(timeout=1) is Phase.UNKNOWN
    assert deadlines == [11.0]


def test_zero_budget_does_not_enter_port(channels, monkeypatch):
    parent, _, port = channels

    def forbidden(deadline):
        pytest.fail("expired budget must not admit IO")

    monkeypatch.setattr(port, "observe", forbidden)
    assert parent.wait(timeout=0) is Phase.UNKNOWN


def test_child_observation_and_cas_share_one_deadline(channels, monkeypatch):
    import loushang.hosting.service_handoff as module

    _, child, port = channels
    now, deadlines = [10.0], []
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    def observe(deadline):
        deadlines.append(deadline)
        now[0] += 0.5
        return Phase.PROVISIONAL

    def commit(deadline):
        deadlines.append(deadline)
        return Phase.COMMITTED

    monkeypatch.setattr(port, "observe", observe)
    monkeypatch.setattr(port, "commit", commit)
    assert child.commit() is Phase.COMMITTED
    assert deadlines == [12.0, 12.0]


def test_close_fences_new_calls_while_admitted_observation_finishes(channels, monkeypatch):
    parent, _, port = channels
    entered, release = threading.Event(), threading.Event()
    results = []

    def observe(deadline):
        entered.set()
        assert release.wait(5)
        return Phase.COMMITTED

    monkeypatch.setattr(port, "observe", observe)
    worker = threading.Thread(target=lambda: results.append(parent.wait(timeout=5)))
    closer = threading.Thread(target=parent.close)
    worker.start()
    try:
        assert entered.wait(5)
        closer.start()
        assert parent._closing.wait(5)
        with pytest.raises(HostingError) as caught:
            parent.wait(timeout=0)
        assert caught.value.category is HostingFailureCategory.HOST_CLOSED
    finally:
        release.set()
        worker.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not worker.is_alive() and not closer.is_alive()
    assert results == [Phase.COMMITTED]
