from __future__ import annotations

import asyncio
import inspect
import subprocess
import sys
from contextlib import suppress
from dataclasses import replace
from typing import cast

import pytest

from loushang.appserver.framing import AsyncioStreamTransportV1
from loushang.appserver.local import (
    LocalAppClientConnectionV1,
    LocalAppServerV1,
    LocalConnectionModeV1,
    OwnedLocalClientScopeV1,
)
from loushang.appserver.local_auth import (
    LocalAuthenticationError,
    authenticate_local_client,
)
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    LocalRecordScopeV1,
)
from loushang.appserver.protocol import AppServiceError, MuxListResultV1, SessionScopeV1


class _Scope:
    def __init__(self):
        self.closed = False
        self.close_release = None

    async def list_muxes(self):
        return MuxListResultV1(())

    async def close(self):
        if self.close_release is not None:
            await self.close_release.wait()
        self.closed = True


def _server(directory, *, auth_timeout=1, close_timeout=1, request_stop=None, instance=None):
    scopes = []
    def factory():
        scope = _Scope()
        scopes.append(scope)
        return cast(OwnedLocalClientScopeV1, scope)
    server = LocalAppServerV1(
        directory, "workspace", application_id="application", product_id="coding",
        scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),), scope_factory=factory,
        request_stop=request_stop or (lambda _: pytest.fail("unexpected application stop")),
        auth_timeout=auth_timeout, close_timeout=close_timeout,
        instance=instance,
    )
    return server, scopes


def test_managed_instance_is_published_and_stale_client_rejects_before_socket(tmp_path, monkeypatch):
    from loushang.appserver import local as module

    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory, instance="c" * 32)
        stale = LocalAppClientConnectionV1(directory, "workspace", expected_instance="d" * 32)
        current = LocalAppClientConnectionV1(directory, "workspace", expected_instance="c" * 32)
        try:
            with pytest.raises(AppServiceError):
                _ = current.application_id
            await server.start()
            assert directory.read("workspace").instance == "c" * 32
            with monkeypatch.context() as patch:
                patch.setattr(module.socket, "socket", lambda *a, **k: pytest.fail("stale reference opened socket"))
                with pytest.raises(AppServiceError):
                    await stale.start()
            assert not scopes
            await current.start()
            assert current.application_id == "application"
            with monkeypatch.context() as patch:
                patch.setattr(directory, "read", lambda *_: pytest.fail("authenticated identity reread mutable record"))
                assert current.application_id == "application"
            assert await current.client.list_muxes() == MuxListResultV1(())
        finally:
            await asyncio.gather(stale.close(), current.close())
            with pytest.raises(AppServiceError):
                _ = current.application_id
            await server.close()
            directory.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["", "C" * 32, "c" * 31, True, 7])
def test_invalid_managed_instance_rejected_before_record_or_socket(tmp_path, value):
    root = tmp_path / "runtime"
    directory = LocalConnectionDirectoryV1(root)
    try:
        with pytest.raises(ValueError):
            _server(directory, instance=value)
        with pytest.raises(ValueError):
            LocalAppClientConnectionV1(directory, "workspace", expected_instance=value)
        assert not root.exists()
    finally:
        directory.close()


async def _until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("stale", [False, True])
def test_managed_prepare_binds_without_publication_or_acceptance(tmp_path, stale):
    root = tmp_path / "runtime"
    if stale:
        # A real crashed writer leaves its record but releases its native lock.
        subprocess.run([sys.executable, "-c", """
import os, socket, sys
from pathlib import Path
from loushang.appserver.local_record import LocalConnectionDirectoryV1, LocalRecordScopeV1
from loushang.appserver.protocol import SessionScopeV1
directory = LocalConnectionDirectoryV1(Path(sys.argv[1]))
reservation = directory.acquire('workspace')
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
reservation.publish(application_id='old', product_id='coding',
                    port=sock.getsockname()[1],
                    scopes=(LocalRecordScopeV1(SessionScopeV1.CWD, 'a' * 64),))
os._exit(0)
""", str(root)], check=True, timeout=10)

    async def scenario():
        directory = LocalConnectionDirectoryV1(root)
        old = directory.read("workspace") if stale else None
        # The non-serving connection probes below may consume their full native
        # timeout on platforms that queue connect() before start_serving().
        # Keep that observation budget distinct from the server startup budget.
        server, scopes = _server(directory, close_timeout=4)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            await server.prepare()
            assert not server._server.is_serving()
            assert server._record is None and scopes == []
            with pytest.raises(AppServiceError):
                _ = server.record
            if old is not None:
                assert directory.read("workspace") == old
            else:
                with pytest.raises(LocalRecordError):
                    directory.read("workspace")
            # Even knowing the prepared native address cannot enter semantics.
            addresses = [server._server.sockets[0].getsockname()]
            if old is not None:
                addresses.append(("127.0.0.1", old.port))
            for address in addresses:
                with pytest.raises(OSError):
                    await asyncio.wait_for(asyncio.open_connection(*address), 1)
            assert scopes == []
            await server.activate()
            if old is not None:
                assert server.record.instance != old.instance
                reader, writer = await asyncio.open_connection("127.0.0.1", server.record.port)
                try:
                    with pytest.raises(LocalAuthenticationError):
                        await authenticate_local_client(
                            AsyncioStreamTransportV1(reader, writer), old.authentication, timeout=1,
                        )
                finally:
                    writer.close()
                    await writer.wait_closed()
                assert scopes == []
            await client.start()
            assert (await client.client.list_muxes()).mux_spaces == ()
            assert len(scopes) == 1
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_managed_prepare_activate_call_order_never_restarts_or_republishes(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, _ = _server(directory)
        try:
            with pytest.raises(AppServiceError):
                await server.activate()
            assert server._start_task is None and not server._closed
            await server.prepare()
            original = server._server
            for call in (server.prepare, server.start):
                with pytest.raises(AppServiceError):
                    await call()
                assert not server._closed
            await server.activate()
            record = server.record
            with pytest.raises(AppServiceError):
                await server.activate()
            assert server._server is original and server.record == record
            await server.close()
            for call in (server.prepare, server.activate, server.start):
                with pytest.raises(AppServiceError):
                    await call()
        finally:
            await server.close()
            directory.close()
    asyncio.run(scenario())


def test_managed_activation_cannot_renew_expired_preparation_budget(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        deadline = asyncio.get_running_loop().time() + 0.1
        try:
            await server.prepare(deadline=deadline)
            assert server._startup_deadline == deadline
            await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()) + 0.01)
            with pytest.raises(AppServiceError):
                await server.activate()
            assert server._startup_deadline == deadline
            assert server._activate_task is None and scopes == []
            assert not directory._leases
            with pytest.raises(LocalRecordError):
                directory.read("workspace")
        finally:
            await server.close()
            directory.close()
    asyncio.run(scenario())


def test_managed_cancelled_activation_retains_late_serving_task(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        # Keep the injected close delay comfortably above cross-platform event
        # loop jitter; this test asserts ownership, not a 50 ms latency bound.
        server, scopes = _server(directory, close_timeout=1)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            await server.prepare()
            native = server._server
            original = native.start_serving

            async def delayed():
                await original()
                entered.set()
                await release.wait()

            monkeypatch.setattr(native, "start_serving", delayed)
            activating = asyncio.create_task(server.activate())
            await entered.wait()
            owned = server._activate_task
            with pytest.raises(AppServiceError):
                await server.activate()
            assert not server._closed  # Invalid second waiter did not fence the first.
            activating.cancel()
            with pytest.raises(AppServiceError):
                await activating
            assert not owned.done() and not owned.cancelled()
            assert not native.is_serving() and scopes == []
            release.set()
            await server.close()
            assert owned.done() and native.sockets == ()
            assert not directory._leases
        finally:
            release.set()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_managed_failed_publication_cleans_its_late_record(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        try:
            await server.prepare()
            original = server._reservation.publish

            def publish_then_fail(**kwargs):
                original(**kwargs)
                raise RuntimeError("injected failure after publication")

            monkeypatch.setattr(server._reservation, "publish", publish_then_fail)
            with pytest.raises(RuntimeError, match="injected failure"):
                await server.activate()
            assert not server._server.is_serving() and scopes == []
            assert not directory._leases
            with pytest.raises(LocalRecordError):
                directory.read("workspace")
        finally:
            await server.close()
            directory.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), -float("inf"), 10**1000, -(10**1000), 0, -1])
def test_managed_invalid_deadline_has_no_startup_effect(tmp_path, deadline):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, _ = _server(directory)
        try:
            with pytest.raises(ValueError):
                await server.prepare(deadline=deadline)
            assert server._start_task is None and server._startup_deadline is None
            assert not (tmp_path / "runtime").exists() and not server._closed
        finally:
            await server.close()
            directory.close()
    asyncio.run(scenario())


def test_one_step_start_reserves_activation_between_stages(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, _ = _server(directory)
        original = server._prepare

        async def competing(**kwargs):
            await original(**kwargs)
            assert server._start_task.done() and server._prepared
            for call in (server.start, server.prepare, server.activate):
                with pytest.raises(AppServiceError):
                    await call()
            assert server._activate_task is None and not server._closed

        monkeypatch.setattr(server, "_prepare", competing)
        try:
            await server.start()
            assert server.record == directory.read("workspace")
            assert server._server.is_serving()
        finally:
            await server.close()
            directory.close()
    asyncio.run(scenario())


def test_G16_LOCAL_AUTH_expected_product_is_checked_on_admitted_record_before_io(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        client = LocalAppClientConnectionV1(directory, "workspace", expected_product_id="slides")
        try:
            await server.start()
            with pytest.raises(AppServiceError):
                await client.start()
            assert client._socket is None
            assert server.connection_counts == (0, 0) and scopes == []
        finally:
            await client.close()
            await server.close()
            directory.close()
    asyncio.run(scenario())


def test_G16_LOCAL_NATIVE_real_authenticated_request_and_client_eof_only_closes_scope(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            with pytest.raises(AppServiceError):
                _ = client.scopes
            await server.start()
            record = directory.read("workspace")
            assert record == server.record
            assert server._server.sockets[0].getsockname() == ("127.0.0.1", record.port)
            await client.start()
            assert client.scopes == record.scopes == (LocalRecordScopeV1(SessionScopeV1.CWD, "a" * 64),)
            assert await client.client.list_muxes() == MuxListResultV1(())
            assert server.connection_counts == (0, 1)
            await client.close()
            with pytest.raises(AppServiceError):
                _ = client.scopes
            await _until(lambda: server.connection_counts == (0, 0))
            assert len(scopes) == 1 and scopes[0].closed
            assert directory.read("workspace") == record
            replacement = LocalAppClientConnectionV1(directory, "workspace")
            try:
                await replacement.start()
                assert await replacement.client.list_muxes() == MuxListResultV1(())
            finally:
                await replacement.close()
        finally:
            await client.close()
            await server.close()
            with pytest.raises(LocalRecordError):
                directory.read("workspace")
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_G16_LOCAL_AUTH_wrong_key_never_constructs_semantics(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        await server.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", server.record.port)
        try:
            wrong = replace(server.record.authentication, key=b"x" * 32)
            with pytest.raises(LocalAuthenticationError):
                await authenticate_local_client(AsyncioStreamTransportV1(reader, writer), wrong)
            await _until(lambda: server.connection_counts == (0, 0))
            assert scopes == []
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_BOUNDS_pending_authentication_is_reserved_before_tasks(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory, auth_timeout=2)
        peers = []
        try:
            await server.start()
            for _ in range(8):
                peers.append(await asyncio.open_connection("127.0.0.1", server.record.port))
            await _until(lambda: server.connection_counts == (8, 0))
            extra = await asyncio.open_connection("127.0.0.1", server.record.port)
            peers.append(extra)
            with suppress(ConnectionResetError):
                assert await asyncio.wait_for(extra[0].read(1), 1) == b""
            assert server.connection_counts == (8, 0)
            assert scopes == []
        finally:
            for _, writer in peers:
                writer.close()
                with suppress(ConnectionError):
                    await writer.wait_closed()
            await server.close()
            assert server.connection_counts == (0, 0)
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 8))


def test_G16_LOCAL_AUTH_idle_peer_expires_without_scope_admission(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory, auth_timeout=0.05)
        try:
            await server.start()
            reader, writer = await asyncio.open_connection("127.0.0.1", server.record.port)
            try:
                assert await asyncio.wait_for(reader.read(), 1)
                await _until(lambda: server.connection_counts == (0, 0))
                assert scopes == []
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_STOP_reserved_slot_and_reply_barrier_avoid_requester_self_wait(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        stop_tasks = []
        stopped = asyncio.Event()
        async def stop_after_reply(reply_finished):
            await reply_finished
            await server.close()
            stopped.set()
        def admit_stop(reply_finished):
            stop_tasks.append(asyncio.create_task(stop_after_reply(reply_finished)))
        server, scopes = _server(directory, request_stop=admit_stop)
        clients = []
        try:
            await server.start()
            for _ in range(7):
                client = LocalAppClientConnectionV1(directory, "workspace")
                clients.append(client)
                await client.start()
            rejected = LocalAppClientConnectionV1(directory, "workspace")
            clients.append(rejected)
            with pytest.raises(AppServiceError):
                await rejected.start()
            stop = LocalAppClientConnectionV1(directory, "workspace", mode=LocalConnectionModeV1.STOP)
            clients.append(stop)
            await stop.start()
            assert stop.stop_requested
            with pytest.raises(AppServiceError):
                _ = stop.client
            await asyncio.wait_for(stopped.wait(), 3)
            assert len(stop_tasks) == 1
            assert len(scopes) == 7 and all(scope.closed for scope in scopes)
            assert server.connection_counts == (0, 0)
        finally:
            await asyncio.gather(*(client.close() for client in clients))
            await server.close()
            await asyncio.gather(*stop_tasks)
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_G16_LOCAL_CLEANUP_debt_keeps_capacity_until_exact_scope_settles(tmp_path):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        # The same bound covers startup and cleanup.  Leave startup enough room
        # on loaded Windows runners while still forcing bounded cleanup debt.
        server, scopes = _server(directory, close_timeout=1)
        client = LocalAppClientConnectionV1(directory, "workspace")
        try:
            await server.start()
            await client.start()
            scopes[0].close_release = asyncio.Event()
            await client.close()
            with pytest.raises(AppServiceError):
                await server.close()
            assert server.connection_counts == (0, 1)
            assert directory.read("workspace")
            scopes[0].close_release.set()
            await server.close()
            assert scopes[0].closed
            assert server.connection_counts == (0, 0)
        finally:
            if scopes and scopes[0].close_release is not None:
                scopes[0].close_release.set()
            await client.close()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_START_cancelled_bind_keeps_late_server_owner(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory, close_timeout=0.05)
        entered, release = asyncio.Event(), asyncio.Event()
        original = asyncio.start_server
        captured = []
        async def delayed(*args, **kwargs):
            native = await original(*args, **kwargs)
            captured.append(native)
            entered.set()
            await release.wait()
            return native
        try:
            with monkeypatch.context() as patch:
                patch.setattr(asyncio, "start_server", delayed)
                starting = asyncio.create_task(server.start())
                await entered.wait()
                starting.cancel()
                with pytest.raises(AppServiceError):
                    await starting
                assert server._socket is not None  # Hand-off is still owned.
                assert scopes == []
                with pytest.raises(LocalRecordError):
                    directory.read("workspace")
                release.set()
                await server.close()
                assert captured[0].sockets == ()
                assert not directory._leases
        finally:
            release.set()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_START_cancelled_client_adopts_and_closes_late_writer(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, scopes = _server(directory)
        client = LocalAppClientConnectionV1(directory, "workspace", timeout=0.05)
        entered, release = asyncio.Event(), asyncio.Event()
        original = asyncio.open_connection
        captured = []
        async def delayed(*args, **kwargs):
            pair = await original(*args, **kwargs)
            captured.append(pair[1])
            entered.set()
            # Deliberately emulate a native adapter completing after timeout.
            while not release.is_set():
                with suppress(asyncio.CancelledError):
                    await release.wait()
            return pair
        try:
            await server.start()
            with monkeypatch.context() as patch:
                patch.setattr(asyncio, "open_connection", delayed)
                starting = asyncio.create_task(client.start())
                await entered.wait()
                starting.cancel()
                with pytest.raises(AppServiceError):
                    await starting
                assert client._start_task is not None and not client._start_task.done()
                release.set()
                await client.close()
                assert captured[0].is_closing()
                await _until(lambda: server.connection_counts == (0, 0))
                assert scopes == []
        finally:
            release.set()
            await client.close()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_STOP_lost_reply_does_not_lose_admitted_stop(tmp_path, monkeypatch):
    from loushang.appserver._local_peer import LOCAL_STOP_ACK
    from loushang.appserver.local_auth import AuthenticatedLocalStreamV1

    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        stop_tasks = []
        async def stop_after_reply(reply_finished):
            await reply_finished
            await server.close()
        def admit(reply_finished):
            stop_tasks.append(asyncio.create_task(stop_after_reply(reply_finished)))
        server, scopes = _server(directory, request_stop=admit)
        client = LocalAppClientConnectionV1(directory, "workspace", mode=LocalConnectionModeV1.STOP)
        original = AuthenticatedLocalStreamV1.send
        async def failed_reply(self, payload):
            if payload == LOCAL_STOP_ACK:
                raise OSError("injected reply loss")
            return await original(self, payload)
        try:
            await server.start()
            with monkeypatch.context() as patch:
                patch.setattr(AuthenticatedLocalStreamV1, "send", failed_reply)
                with pytest.raises(AppServiceError):
                    await client.start()
            assert not client.stop_requested
            assert len(stop_tasks) == 1
            await asyncio.gather(*stop_tasks)
            assert scopes == [] and server.connection_counts == (0, 0)
            with pytest.raises(LocalRecordError):
                directory.read("workspace")
        finally:
            await client.close()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G16_LOCAL_START_task_factory_failure_closes_unstarted_coroutine(tmp_path, monkeypatch):
    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        server, _ = _server(directory)
        captured = []
        def broken(work):
            captured.append(work)
            raise RuntimeError("injected task factory failure")
        try:
            with monkeypatch.context() as patch:
                patch.setattr(asyncio, "create_task", broken)
                with pytest.raises(RuntimeError):
                    await server.start()
            assert captured
            assert all(inspect.getcoroutinestate(work) == inspect.CORO_CLOSED for work in captured)
            assert not (tmp_path / "runtime").exists()
        finally:
            for work in captured:
                work.close()
            await server.close()
            directory.close()
    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("kind", ["listener", "client", "stop"])
def test_G16_LOCAL_READY_settlement_before_start_delivery_cannot_announce_ready(
    tmp_path, monkeypatch, kind,
):
    import loushang.appserver.local as local

    async def scenario():
        directory = LocalConnectionDirectoryV1(tmp_path / "runtime")
        stops = []
        server, scopes = _server(directory, request_stop=stops.append)
        client = LocalAppClientConnectionV1(directory, "workspace")
        owner = client if kind == "client" else server
        join = local._join_close

        async def settle_before_delivery(task, timeout):
            await join(task, timeout)
            if task is owner._start_task:
                if kind == "stop":
                    reply = asyncio.get_running_loop().create_future()
                    reply.set_result(None)
                    server._admit_stop(reply)
                else:
                    await owner.close()

        try:
            if kind == "client":
                await server.start()
            with monkeypatch.context() as patch:
                patch.setattr(local, "_join_close", settle_before_delivery)
                with pytest.raises(AppServiceError) as closed:
                    await owner.start()
                assert closed.value.code.value == "service_closed"
            assert owner._start_task.done() and owner._closed
            if kind == "stop":
                assert len(stops) == 1 and server._stop_requested
            if kind == "client":
                with pytest.raises(AppServiceError):
                    _ = client.client
                with pytest.raises(AppServiceError):
                    _ = client.scopes
            else:
                assert scopes == []
                with pytest.raises(LocalRecordError):
                    directory.read("workspace")
        finally:
            await client.close()
            await server.close()
            directory.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("descriptor", [-1, 123])
def test_G16_LOCAL_CLEANUP_reset_requires_actual_handle_closed_evidence(descriptor):
    from loushang.appserver.local import _LocalTransport

    class Writer:
        def close(self):
            pass
        async def wait_closed(self):
            raise ConnectionResetError("injected reset")
        def get_extra_info(self, name):
            assert name == "socket"
            return self
        def fileno(self):
            return descriptor
    async def scenario():
        transport = _LocalTransport(asyncio.StreamReader(), Writer())
        if descriptor == -1:
            await transport.close()
        else:
            with pytest.raises(AppServiceError) as debt:
                await transport.close()
            assert debt.value.code.value == "cleanup_incomplete"
    asyncio.run(scenario())
