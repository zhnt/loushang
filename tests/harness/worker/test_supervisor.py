from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.worker.protocol import (
    WorkerFrameCodec,
    WorkerFramedTransport,
    WorkerProtocolMessage,
)
from loushang.harness.worker.supervisor import (
    WorkerSupervisor,
    WorkerSupervisorError,
    WorkerSupervisorLimitsV1,
)
from loushang.harness.workspace.process import ProcessExit, ProcessStderrTail


class _ScriptedByteTransport:
    def __init__(self) -> None:
        self._incoming = bytearray()
        self._changed = asyncio.Event()
        self.closed = False
        self.writes: list[bytes] = []

    def feed(self, message: WorkerProtocolMessage) -> None:
        self._incoming.extend(WorkerFrameCodec.encode(message))
        self._changed.set()

    async def read_exactly(self, size: int) -> bytes:
        while len(self._incoming) < size:
            if self.closed:
                raise EOFError
            self._changed.clear()
            await self._changed.wait()
        body = bytes(self._incoming[:size])
        del self._incoming[:size]
        return body

    async def write(self, body: bytes) -> None:
        self.writes.append(body)
        self._changed.set()

    async def close(self) -> None:
        self.closed = True
        self._changed.set()

    async def wait_for_writes(self, count: int) -> None:
        while len(self.writes) < count:
            self._changed.clear()
            await self._changed.wait()

    def written_message(self, ordinal: int) -> WorkerProtocolMessage:
        frame = self.writes[ordinal]
        size = WorkerFrameCodec.decode_header(frame[:4])
        return WorkerFrameCodec.decode_body(frame[4:], expected_size=size)


class _Process:
    def __init__(self) -> None:
        self._exit: asyncio.Future[ProcessExit] = (
            asyncio.get_running_loop().create_future()
        )
        self.terminated = False

    def finish(self, return_code: int) -> None:
        if not self._exit.done():
            self._exit.set_result(ProcessExit(return_code))

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return b""

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return b""

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return await asyncio.shield(self._exit)

    async def terminate(self) -> ProcessExit:
        self.terminated = True
        self.finish(-15)
        return await self.wait()

    async def close(self) -> None:
        await self.terminate()

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail()


class _LaunchPort:
    def __init__(self, process: _Process) -> None:
        self.process = process
        self.requests: list[ManagedWorkerLaunchRequestV1] = []

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> _Process:
        del correlation_id, signal
        self.requests.append(request)
        return self.process


def _runtime(tmp_path: Path) -> WorkerRuntimeBindingV1:
    executable = tmp_path / "worker"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o500)
    return WorkerRuntimeBindingV1.capture(
        package_root=tmp_path,
        configuration=PluginLocalWorkerConfiguration(
            entrypoint="worker",
            protocol="capability.query",
            protocol_version=1,
        ),
    )


def _identity(runtime: WorkerRuntimeBindingV1) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="review-pack",
        plugin_revision_digest="a" * 64,
        contribution_id="review-provider",
        owner_id="coding.lsp",
        product_id="coding",
        scope_id="session-one",
        owner_generation=3,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint=(runtime.worker_configuration_fingerprint),
        attempt_id="c" * 32,
        supervisor_epoch=1,
        session_nonce="d" * 64,
    )


def _ready(identity: WorkerLaunchIdentityV1) -> WorkerProtocolMessage:
    return WorkerProtocolMessage.create(
        "ready",
        attemptId=identity.attempt_id,
        identityFingerprint=identity.fingerprint,
        protocol="capability.query",
        protocolVersion=1,
        sessionNonce=identity.session_nonce,
        supervisorEpoch=identity.supervisor_epoch,
    )


def _ids() -> Iterator[str]:
    for char in "123456789abcdef":
        yield char * 32


def test_supervisor_handshake_query_heartbeat_and_ordered_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        request = ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=runtime,
            validate_current=lambda: None,
        )
        process = _Process()
        port = _LaunchPort(process)
        byte_transport = _ScriptedByteTransport()
        byte_transport.feed(_ready(identity))
        ids = _ids()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            correlation_id_factory=lambda: next(ids),
        )

        await supervisor.start(
            launch_port=port,  # type: ignore[arg-type]
            launch_request=request,
            transport=WorkerFramedTransport(byte_transport),
            correlation_id="launch-one",
        )
        assert supervisor.status.state == "healthy"
        assert byte_transport.written_message(0).kind == "start"

        query_task = asyncio.create_task(supervisor.query({"operation": "describe"}))
        await byte_transport.wait_for_writes(2)
        query = byte_transport.written_message(1)
        correlation = query.fields["correlationId"]
        byte_transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=correlation,
                payload={"capabilities": ["hover"]},
            )
        )
        assert await query_task == {"capabilities": ["hover"]}

        heartbeat_task = asyncio.create_task(supervisor.heartbeat())
        await byte_transport.wait_for_writes(3)
        heartbeat = byte_transport.written_message(2)
        byte_transport.feed(
            WorkerProtocolMessage.create(
                "pong",
                heartbeatId=heartbeat.fields["heartbeatId"],
            )
        )
        await heartbeat_task

        shutdown_task = asyncio.create_task(supervisor.shutdown())
        await byte_transport.wait_for_writes(4)
        assert byte_transport.written_message(3).kind == "shutdown"
        byte_transport.feed(WorkerProtocolMessage.create("shutdown_ack"))
        process.finish(0)
        await shutdown_task

        assert supervisor.status.state == "stopped"
        assert supervisor.status.failure_code is None

    asyncio.run(scenario())


def test_late_reply_after_timeout_fences_attempt_and_terminates_process(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        byte_transport = _ScriptedByteTransport()
        byte_transport.feed(_ready(identity))
        ids = _ids()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            limits=WorkerSupervisorLimitsV1(query_timeout_seconds=0.01),
            correlation_id_factory=lambda: next(ids),
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(byte_transport),
            correlation_id="launch-one",
        )

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.query({"operation": "slow"})
        assert caught.value.code == "worker_query_timeout"
        await byte_transport.wait_for_writes(3)
        query = byte_transport.written_message(1)
        assert byte_transport.written_message(2).kind == "cancel"

        byte_transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={"late": True},
            )
        )
        for _ in range(20):
            if supervisor.status.state == "fenced":
                break
            await asyncio.sleep(0)

        assert supervisor.status.state == "fenced"
        assert (
            supervisor.status.failure_code
            == "worker_protocol_reply_correlation_invalid"
        )
        assert process.terminated is True

    asyncio.run(scenario())


def test_handshake_identity_mismatch_never_becomes_healthy(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        byte_transport = _ScriptedByteTransport()
        mismatched = _ready(identity).to_dict()
        mismatched["sessionNonce"] = "e" * 64
        byte_transport.feed(WorkerProtocolMessage.from_dict(mismatched))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.start(
                launch_port=_LaunchPort(process),  # type: ignore[arg-type]
                launch_request=ManagedWorkerLaunchRequestV1(
                    identity=identity,
                    runtime=runtime,
                    validate_current=lambda: None,
                ),
                transport=WorkerFramedTransport(byte_transport),
                correlation_id="launch-one",
            )

        assert caught.value.code == "worker_protocol_handshake_mismatch"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_supervisor_rejects_protocol_binding_mismatch_before_claim(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        port = _LaunchPort(process)
        transport = _ScriptedByteTransport()
        journal_path = tmp_path / "workers.jsonl"
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(journal_path),
            protocol="capability.other",
            protocol_version=1,
        )

        with pytest.raises(ValueError, match="runtime binding"):
            await supervisor.start(
                launch_port=port,  # type: ignore[arg-type]
                launch_request=ManagedWorkerLaunchRequestV1(
                    identity=identity,
                    runtime=runtime,
                    validate_current=lambda: None,
                ),
                transport=WorkerFramedTransport(transport),
                correlation_id="launch-one",
            )
        assert port.requests == []
        assert not journal_path.exists()
        assert transport.closed is False

    asyncio.run(scenario())


def test_supervisor_rejects_invalid_launch_wiring_before_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        journal_path = tmp_path / "workers.jsonl"
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(journal_path),
            protocol="capability.query",
            protocol_version=1,
        )
        request = ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=runtime,
            validate_current=lambda: None,
        )

        with pytest.raises(TypeError, match="launch port"):
            await supervisor.start(
                launch_port=object(),  # type: ignore[arg-type]
                launch_request=request,
                transport=WorkerFramedTransport(_ScriptedByteTransport()),
                correlation_id="launch-one",
            )
        assert not journal_path.exists()

    asyncio.run(scenario())


def test_handshake_timeout_is_distinct_and_fences_attempt(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            limits=WorkerSupervisorLimitsV1(handshake_timeout_seconds=0.01),
        )

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.start(
                launch_port=_LaunchPort(process),  # type: ignore[arg-type]
                launch_request=ManagedWorkerLaunchRequestV1(
                    identity=identity,
                    runtime=runtime,
                    validate_current=lambda: None,
                ),
                transport=WorkerFramedTransport(_ScriptedByteTransport()),
                correlation_id="launch-one",
            )

        assert caught.value.code == "worker_handshake_timeout"
        assert supervisor.status.failure_code == "worker_handshake_timeout"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_launch_cancellation_is_not_collapsed_into_launch_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        entered = asyncio.Event()

        class BlockingLaunchPort:
            async def start(self, request, *, correlation_id, signal=None):
                del request, correlation_id, signal
                entered.set()
                await asyncio.Future()

        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )
        byte_transport = _ScriptedByteTransport()
        task = asyncio.create_task(
            supervisor.start(
                launch_port=BlockingLaunchPort(),  # type: ignore[arg-type]
                launch_request=ManagedWorkerLaunchRequestV1(
                    identity=identity,
                    runtime=runtime,
                    validate_current=lambda: None,
                ),
                transport=WorkerFramedTransport(byte_transport),
                correlation_id="launch-one",
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert supervisor.status.state == "failed"
        assert supervisor.status.failure_code == "worker_launch_cancelled"
        assert byte_transport.closed is True

    asyncio.run(scenario())


def test_shutdown_refuses_pending_work_and_fences_nonzero_exit(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        ids = _ids()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            correlation_id_factory=lambda: next(ids),
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )

        query = asyncio.create_task(supervisor.query({"operation": "describe"}))
        await transport.wait_for_writes(2)
        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.shutdown()
        assert caught.value.code == "worker_shutdown_work_pending"
        assert supervisor.status.state == "healthy"

        request = transport.written_message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=request.fields["correlationId"],
                payload={},
            )
        )
        await query
        shutdown = asyncio.create_task(supervisor.shutdown())
        await transport.wait_for_writes(3)
        transport.feed(WorkerProtocolMessage.create("shutdown_ack"))
        process.finish(7)
        with pytest.raises(WorkerSupervisorError) as caught:
            await shutdown
        assert caught.value.code == "worker_shutdown_exit_failed"
        assert supervisor.status.state == "fenced"
        assert supervisor.status.failure_code == "worker_shutdown_exit_failed"

    asyncio.run(scenario())


def test_query_cancellation_accepts_one_ack_but_rejects_later_result(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        ids = _ids()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            correlation_id_factory=lambda: next(ids),
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )
        query = asyncio.create_task(supervisor.query({"operation": "describe"}))
        await transport.wait_for_writes(2)
        request = transport.written_message(1)
        correlation_id = request.fields["correlationId"]
        query.cancel()
        with pytest.raises(asyncio.CancelledError):
            await query
        await transport.wait_for_writes(3)
        assert transport.written_message(2).kind == "cancel"
        transport.feed(
            WorkerProtocolMessage.create(
                "cancelled",
                correlationId=correlation_id,
            )
        )
        await asyncio.sleep(0)
        assert supervisor.status.state == "healthy"
        assert supervisor.status.cancellation_tombstones == 1

        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=correlation_id,
                payload={},
            )
        )
        for _ in range(20):
            if supervisor.status.state == "fenced":
                break
            await asyncio.sleep(0)
        assert supervisor.status.failure_code == (
            "worker_protocol_reply_correlation_invalid"
        )
        assert process.terminated is True

    asyncio.run(scenario())


def test_heartbeat_timeout_and_unexpected_exit_fence_distinct_attempts(
    tmp_path: Path,
) -> None:
    async def heartbeat_scenario() -> None:
        runtime = _runtime(tmp_path / "heartbeat")
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "heartbeat.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            limits=WorkerSupervisorLimitsV1(heartbeat_timeout_seconds=0.01),
            correlation_id_factory=lambda: "1" * 32,
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )
        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.heartbeat()
        assert caught.value.code == "worker_heartbeat_timeout"
        assert supervisor.status.failure_code == "worker_heartbeat_timeout"
        assert process.terminated is True

    async def crash_scenario() -> None:
        runtime = _runtime(tmp_path / "crash")
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "crash.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            correlation_id_factory=lambda: "2" * 32,
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )
        query = asyncio.create_task(supervisor.query({"operation": "describe"}))
        await transport.wait_for_writes(2)
        process.finish(137)
        with pytest.raises(WorkerSupervisorError) as caught:
            await query
        assert caught.value.code == "worker_process_exited"
        assert supervisor.status.failure_code == "worker_process_exited"

    (tmp_path / "heartbeat").mkdir()
    (tmp_path / "crash").mkdir()
    asyncio.run(heartbeat_scenario())
    asyncio.run(crash_scenario())


def test_supervisor_enforces_in_flight_and_session_message_budgets(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        ids = _ids()
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            limits=WorkerSupervisorLimitsV1(
                max_in_flight=1,
                max_messages_per_session=1,
            ),
            correlation_id_factory=lambda: next(ids),
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )
        first = asyncio.create_task(supervisor.query({"ordinal": 1}))
        await transport.wait_for_writes(2)
        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.query({"ordinal": 2})
        assert caught.value.code == "worker_request_queue_full"
        request = transport.written_message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=request.fields["correlationId"],
                payload={},
            )
        )
        await first

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.query({"ordinal": 3})
        assert caught.value.code == "worker_message_budget_exhausted"
        await supervisor.fence(code="test_complete")

    asyncio.run(scenario())


def test_supervisor_limit_values_are_themselves_bounded() -> None:
    with pytest.raises(ValueError, match="supported bound"):
        WorkerSupervisorLimitsV1(max_in_flight=1025)
    with pytest.raises(ValueError, match="supported bound"):
        WorkerSupervisorLimitsV1(query_timeout_seconds=math.inf)
    with pytest.raises(ValueError, match="supported bound"):
        WorkerSupervisorLimitsV1(shutdown_timeout_seconds=3601)


def test_shutdown_ack_and_process_exit_timeouts_are_distinct(tmp_path: Path) -> None:
    async def scenario(*, acknowledge: bool, expected_code: str, suffix: str) -> None:
        root = tmp_path / suffix
        root.mkdir()
        runtime = _runtime(root)
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(root / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
            limits=WorkerSupervisorLimitsV1(shutdown_timeout_seconds=0.01),
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity,
                runtime=runtime,
                validate_current=lambda: None,
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="launch-one",
        )
        task = asyncio.create_task(supervisor.shutdown())
        await transport.wait_for_writes(2)
        if acknowledge:
            transport.feed(WorkerProtocolMessage.create("shutdown_ack"))
        with pytest.raises(WorkerSupervisorError) as caught:
            await task
        assert caught.value.code == expected_code
        assert supervisor.status.state == "fenced"
        assert supervisor.status.failure_code == expected_code
        assert process.terminated is True

    asyncio.run(
        scenario(
            acknowledge=False,
            expected_code="worker_shutdown_timeout",
            suffix="ack",
        )
    )
    asyncio.run(
        scenario(
            acknowledge=True,
            expected_code="worker_shutdown_exit_timeout",
            suffix="exit",
        )
    )


def test_healthy_journal_failure_fences_and_cleans_owned_resources(
    tmp_path: Path,
) -> None:
    class FailingJournal(WorkerSupervisorJournal):
        def transition(self, attempt_id: str, **kwargs: object):  # type: ignore[no-untyped-def]
            if kwargs.get("next_phase") == "healthy":
                raise OSError("durable journal unavailable")
            return super().transition(attempt_id, **kwargs)  # type: ignore[arg-type]

    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        identity = _identity(runtime)
        process = _Process()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=FailingJournal(tmp_path / "workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.start(
                launch_port=_LaunchPort(process),  # type: ignore[arg-type]
                launch_request=ManagedWorkerLaunchRequestV1(
                    identity=identity,
                    runtime=runtime,
                    validate_current=lambda: None,
                ),
                transport=WorkerFramedTransport(transport),
                correlation_id="launch-one",
            )
        assert caught.value.code == "worker_supervisor_journal_failed"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True
        assert transport.closed is True

    asyncio.run(scenario())
