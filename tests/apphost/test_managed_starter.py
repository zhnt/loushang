from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.registry import ManagedMuxReservationV1, ManagedRegistryV1
from loushang.apphost.managed.starter import ManagedServiceStarterV1
from loushang.hosting.contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed starter")


@pytest.fixture
def owners(tmp_path, request):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), os.geteuid() + getattr(request, "param", 0), "a" * 32)
    service = ManagedServiceKeyV1("coding", str(tmp_path))
    runtime = str(tmp_path / "runtime")
    paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime)
    for root in (paths.registry, paths.lifecycle):
        directory = PrivateManagedDirectory(Path(root), create=True, create_parents=True)
        directory.close()
    registry = ManagedRegistryV1(Path(paths.registry), namespace, create=True)
    registry.reserve_mux(ManagedMuxReservationV1("main", service, "b" * 32))
    journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle), create=True)
    try:
        yield journal, namespace, service, runtime
    finally:
        journal.close()
        registry.close()


def request(invocation, fd):
    # The child creates no descendants/Product. EOF from starter close ends it.
    code = "import socket,sys; s=socket.socket(fileno=int(sys.argv[1])); s.recv(1); s.close()"
    return ProcessLaunchRequest(
        (sys.executable, "-c", code, str(fd)), invocation.service.workspace,
        tuple(os.environ.items()),
        ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD),
    )


def starter(owners, callback=request):
    journal, namespace, service, runtime = owners
    return ManagedServiceStarterV1(journal, namespace, service, runtime_root=runtime, request_factory=callback)


def close_and_reap(owner):
    process = owner._process
    owner.close()
    if process is not None and process._process is not None:
        assert process._process.wait(timeout=5) == 0


def test_invalid_scratch_rejected_before_durable_prepare(owners):
    journal, namespace, service, runtime = owners
    before = journal.read()
    with pytest.raises(ManagedContractError):
        ManagedServiceStarterV1(journal, namespace, service, runtime_root=runtime, request_factory=request,
                                temporary_override="relative")
    assert journal.read() == before


@pytest.mark.parametrize("trace_deadline", [None, 123456789])
def test_real_spawn_registers_once_and_close_does_not_fabricate_stop(owners, trace_deadline):
    calls = []

    def build(invocation, fd):
        state = owners[0].read()
        assert state.handoff.instance == invocation.instance
        calls.append(invocation)
        return request(invocation, fd)

    journal, namespace, service, runtime = owners
    owner = ManagedServiceStarterV1(journal, namespace, service, runtime_root=runtime,
                                   request_factory=build, trace_deadline_ms=trace_deadline)
    competing = starter(owners, build)
    try:
        state = owner.start(expected=None, deadline=monotonic() + 10)
        assert len(calls) == 1 and state.native_identity is not None
        assert not state.cleanly_stopped and state.handoff.phase.value == "provisional"
        assert owner.register_birth(deadline=monotonic() + 5) == state
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.start(expected=None, deadline=monotonic() + 5)
        with pytest.raises(ManagedStorageError, match="conflict"):
            competing.start(expected=None, deadline=monotonic() + 5)
        assert len(calls) == 1 and competing._process is None
        assert calls[0].instance.instance_id in str(owner._layout.paths.temporary)
        assert calls[0].trace_deadline_ms == trace_deadline
    finally:
        close_and_reap(owner)
        competing.close()
    assert not owner.cleanup_pending
    assert owner.observe(deadline=monotonic() + 5) == state


def test_lost_birth_reply_reconciles_without_spawning_again(owners, monkeypatch):
    owner = starter(owners)
    journal = owners[0]
    original = journal.register_native
    calls = []

    def lost(*args, **kwargs):
        calls.append(1)
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(journal, "register_native", lost)
    try:
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.start(expected=None, deadline=monotonic() + 10)
        identity = owner._process.identity
        assert owner.register_birth(deadline=monotonic() + 5).native_identity == identity
        assert calls == [1]
    finally:
        close_and_reap(owner)


def test_callback_stop_fences_native_spawn(owners):
    def stop(invocation, fd):
        owners[0].request_stop(invocation.instance)
        return request(invocation, fd)

    owner = starter(owners, stop)
    try:
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.start(expected=None, deadline=monotonic() + 10)
        assert owner._process is None and owner.observe(deadline=monotonic() + 5).handoff.stop_requested
    finally:
        owner.close()
    assert not owner.cleanup_pending


def test_lost_prepare_reply_never_authorizes_spawn_or_replay(owners, monkeypatch):
    journal = owners[0]
    original = journal.prepare
    calls = []

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")

    monkeypatch.setattr(journal, "prepare", lost)
    owner = starter(owners, lambda *args: calls.append(1))
    try:
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.start(expected=None, deadline=monotonic() + 5)
        assert owner.observe(deadline=monotonic() + 5).native_identity is None
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.start(expected=None, deadline=monotonic() + 5)
        assert not calls and not owner.cleanup_pending
    finally:
        owner.close()


def test_lost_control_root_is_not_recreated(owners, monkeypatch):
    journal = owners[0]
    original = journal.prepare
    fence = journal._fence._root

    def move(*args, **kwargs):
        state = original(*args, **kwargs)
        fence.rename(fence.with_name(fence.name + "-moved"))
        return state

    monkeypatch.setattr(journal, "prepare", move)
    owner = starter(owners)
    try:
        with pytest.raises(ManagedStorageError):
            owner.start(expected=None, deadline=monotonic() + 5)
        assert not fence.exists() and owner._process is None
    finally:
        owner.close()


@pytest.mark.parametrize("operation", ["start", "register_birth"])
def test_close_between_initial_check_and_mutex_never_mutates(owners, monkeypatch, operation):
    owner = starter(owners)
    entered, release = Event(), Event()
    original = owner._check
    calls = []

    def delayed(deadline):
        original(deadline)
        if not calls:
            calls.append(1)
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(owner, "_check", delayed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            owner.start if operation == "start" else owner.register_birth,
            **({"expected": None} if operation == "start" else {}), deadline=monotonic() + 10,
        )
        try:
            assert entered.wait(5)
            owner.close()
            release.set()
            with pytest.raises(ManagedStorageError, match="closed"):
                future.result(timeout=5)
            assert owners[0].read() is None and not owner.cleanup_pending
        finally:
            release.set()
            owner.close()


def test_close_during_final_provisional_read_rejects_native_spawn(owners, monkeypatch):
    owner = starter(owners)
    original = owner._require_provisional
    entered, release = Event(), Event()
    calls = []

    def delayed(deadline):
        original(deadline)
        calls.append(1)
        if len(calls) == 2:
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(owner, "_require_provisional", delayed)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(owner.start, expected=None, deadline=monotonic() + 10)
        try:
            assert entered.wait(5)
            with pytest.raises(ManagedStorageError, match="busy"):
                owner.close()
            release.set()
            with pytest.raises(ManagedStorageError, match="closed"):
                future.result(timeout=5)
            assert owner._process.identity is None and owner._process._process is None
        finally:
            release.set()
            future.result(timeout=5) if not future.done() else None
            owner.close()
    assert not owner.cleanup_pending


@pytest.mark.parametrize("owners", [1], indirect=True)
def test_foreign_uid_namespace_rejected_before_start(owners):
    with pytest.raises(ManagedContractError):
        starter(owners)
    assert owners[0].read() is None


def test_failure_after_real_spawn_retains_process_for_registration(owners, monkeypatch):
    from loushang.hosting.service_process import LinuxServiceProcessV1

    original = LinuxServiceProcessV1.spawn
    calls = []

    def lost(process):
        calls.append(original(process))
        raise OSError("lost native return")

    monkeypatch.setattr(LinuxServiceProcessV1, "spawn", lost)
    owner = starter(owners)
    try:
        with pytest.raises(OSError, match="lost native return"):
            owner.start(expected=None, deadline=monotonic() + 10)
        assert owner.cleanup_pending and owner._process.identity == calls[0]
        assert owner.register_birth(deadline=monotonic() + 5).native_identity == calls[0]
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.start(expected=None, deadline=monotonic() + 5)
        assert len(calls) == 1
    finally:
        close_and_reap(owner)


def test_close_failure_still_closes_parent_and_layout_then_retries_original_process(owners, monkeypatch):
    from loushang.hosting.service_process import LinuxServiceProcessV1

    owner = starter(owners)
    owner.start(expected=None, deadline=monotonic() + 10)
    process = owner._process
    original = LinuxServiceProcessV1.close
    calls = []

    def unavailable(selected):
        calls.append(selected)
        if len(calls) == 1:
            raise OSError("process close unavailable")
        original(selected)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(LinuxServiceProcessV1, "close", unavailable)
            with pytest.raises(OSError, match="process close unavailable"):
                owner.close()
            assert owner._endpoints[0].fileno() == -1
            assert not owner._layout.cleanup_pending and owner.cleanup_pending
            owner.close()
            assert calls == [process, process] and not owner.cleanup_pending
    finally:
        close_and_reap(owner)


def test_unknown_socket_close_is_retained_without_retry(owners, monkeypatch):
    import socket

    owner = starter(owners)
    owner.start(expected=None, deadline=monotonic() + 10)
    parent = owner._endpoints[0]
    original = socket.socket.close
    calls = []

    def unknown(endpoint):
        original(endpoint)
        if endpoint is parent:
            calls.append(1)
            raise OSError("close outcome unknown")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "close", unknown)
            with pytest.raises(OSError, match="close outcome unknown"):
                owner.close()
            assert owner._process.handles_closed and not owner._layout.cleanup_pending
            with pytest.raises(ManagedStorageError, match="unavailable"):
                owner.close()
            assert calls == [1] and owner.cleanup_pending
    finally:
        # The injected failure happened after actual close, so no native fd is
        # leaked. Unknown authority remains unknown, even after child exit.
        assert owner._process._process.wait(timeout=5) == 0


@pytest.mark.parametrize("failure", ["callback", "deadline"])
def test_callback_failure_or_expired_budget_never_spawns(owners, monkeypatch, failure):
    from loushang.apphost.managed import _files

    deadline = monotonic() + 10

    def failed(invocation, fd):
        if failure == "callback":
            raise ValueError("request construction failed")
        value = request(invocation, fd)
        monkeypatch.setattr(_files, "monotonic", lambda: deadline + 1)
        return value

    owner = starter(owners, failed)
    try:
        with pytest.raises((ValueError, ManagedStorageError)):
            owner.start(expected=None, deadline=deadline)
        assert owner._process is None
        monkeypatch.undo()
        assert owner.observe(deadline=monotonic() + 5).native_identity is None
    finally:
        owner.close()
