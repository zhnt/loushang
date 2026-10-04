from __future__ import annotations

import asyncio
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
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdapterError,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.facet_proxy import (
    CapabilityWorkerFacetProxyError,
    CapabilityWorkerReadOnlyFacetProxy,
)
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.worker.protocol import (
    WorkerFrameCodec,
    WorkerFramedTransport,
    WorkerProtocolMessage,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.harness.workspace.process import ProcessExit


class _Transport:
    def __init__(self) -> None:
        self.incoming = bytearray()
        self.changed = asyncio.Event()
        self.writes: list[bytes] = []
        self.closed = False

    def feed(self, message: WorkerProtocolMessage) -> None:
        self.incoming.extend(WorkerFrameCodec.encode(message))
        self.changed.set()

    async def read_exactly(self, size: int) -> bytes:
        while len(self.incoming) < size:
            if self.closed:
                raise EOFError
            self.changed.clear()
            await self.changed.wait()
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result

    async def write(self, body: bytes) -> None:
        self.writes.append(body)
        self.changed.set()

    async def close(self) -> None:
        self.closed = True
        self.changed.set()

    async def wait_for_writes(self, count: int) -> None:
        while len(self.writes) < count:
            self.changed.clear()
            await self.changed.wait()

    def message(self, index: int) -> WorkerProtocolMessage:
        frame = self.writes[index]
        size = WorkerFrameCodec.decode_header(frame[:4])
        return WorkerFrameCodec.decode_body(frame[4:], expected_size=size)


class _Process:
    def __init__(self) -> None:
        self.exit = asyncio.get_running_loop().create_future()
        self.terminated = False

    async def wait(self) -> ProcessExit:
        return await asyncio.shield(self.exit)

    async def terminate(self) -> ProcessExit:
        self.terminated = True
        if not self.exit.done():
            self.exit.set_result(ProcessExit(-15))
        return await self.wait()

    async def close(self) -> None:
        await self.terminate()


class _Port:
    def __init__(self, process: _Process) -> None:
        self.process = process

    async def start(self, request, *, correlation_id, signal=None):
        del request, correlation_id, signal
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
        scope_id="workspace:" + "a" * 64,
        owner_generation=3,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint=runtime.worker_configuration_fingerprint,
        attempt_id="c" * 32,
        supervisor_epoch=1,
        session_nonce="d" * 64,
    )


def _authority() -> CapabilityWorkerAuthorityV1:
    return CapabilityWorkerAuthorityV1(
        plugin_revision_digest="a" * 64,
        declaration_fingerprint="b" * 64,
        owner_generation=3,
        product_policy_revision="policy-1",
        owner_policy_revision="owner-1",
        revocation_epoch=2,
    )


async def _healthy_supervisor(
    tmp_path: Path,
) -> tuple[WorkerSupervisor, _Transport, _Process]:
    runtime = _runtime(tmp_path)
    identity = _identity(runtime)
    transport = _Transport()
    transport.feed(
        WorkerProtocolMessage.create(
            "ready",
            attemptId=identity.attempt_id,
            identityFingerprint=identity.fingerprint,
            protocol="capability.query",
            protocolVersion=1,
            sessionNonce=identity.session_nonce,
            supervisorEpoch=identity.supervisor_epoch,
        )
    )
    process = _Process()
    correlation_ids = iter((char * 32 for char in "123456789abcdef"))
    supervisor = WorkerSupervisor(
        identity=identity,
        journal=WorkerSupervisorJournal(tmp_path / "workers.jsonl"),
        protocol="capability.query",
        protocol_version=1,
        correlation_id_factory=lambda: next(correlation_ids),
    )
    await supervisor.start(
        launch_port=_Port(process),  # type: ignore[arg-type]
        launch_request=ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=runtime,
            validate_current=lambda: None,
        ),
        transport=WorkerFramedTransport(transport),
        correlation_id="launch-one",
    )
    return supervisor, transport, process


def _adapter(
    supervisor: WorkerSupervisor,
    current: list[CapabilityWorkerAuthorityV1],
) -> CapabilityQueryWorkerAdapter:
    return bind_capability_query_worker_adapter(
        supervisor=supervisor,
        binding=_domain_binding(),
        authority_reader=lambda: current[0],
        enabled=True,
    )


def _domain_binding() -> CapabilityWorkerBindingV1:
    return CapabilityWorkerBindingV1(
        plugin_id="review-pack",
        contribution_id="review-provider",
        product_id="coding",
        scope_id="workspace:" + "a" * 64,
        owner_id="coding.lsp",
        allowed_capability_ids=("coding.hover", "coding.symbols"),
        authority=_authority(),
    )


def test_capability_adapter_requires_domain_admission_and_returns_typed_read_only_data(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, _process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            bind_capability_query_worker_adapter(
                supervisor=supervisor,
                binding=_domain_binding(),
                authority_reader=lambda: current[0],
            )
        assert caught.value.code == "worker_disabled_by_policy"
        adapter = _adapter(supervisor, current)

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await adapter.describe()
        assert caught.value.code == "worker_capability_not_admitted"

        admission = adapter.admit()
        query_task = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        query = transport.message(1)
        assert query.to_dict()["payload"] == {
            "admissionFingerprint": admission.fingerprint,
            "allowedCapabilityIds": ["coding.hover", "coding.symbols"],
            "operation": "describe",
            "queryVersion": 1,
        }
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": "coding.hover",
                            "descriptorVersion": 1,
                            "facetIds": ["documentation", "hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        descriptors = await query_task

        assert tuple(item.to_dict() for item in descriptors) == (
            {
                "capabilityId": "coding.hover",
                "descriptorVersion": 1,
                "facetIds": ["documentation", "hover"],
            },
        )
        assert not hasattr(adapter, "publish")
        assert not hasattr(adapter, "retire")
        await supervisor.fence(code="test_complete")

    asyncio.run(scenario())


def test_capability_adapter_invokes_only_owner_granted_described_facet(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        admission = adapter.admit()
        describe = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        description_query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=description_query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": "coding.hover",
                            "descriptorVersion": 1,
                            "facetIds": ["hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        await describe
        grant = CapabilityWorkerFacetGrantV1(
            capability_id="coding.hover",
            facet_id="hover",
            binding_fingerprint=adapter._binding.fingerprint,
            authority_fingerprint=current[0].fingerprint,
            owner_policy_revision=current[0].owner_policy_revision,
        )

        def decode(value: object) -> str:
            if type(value) is not dict or set(value) != {"text"}:
                raise ValueError("invalid hover result")
            text = value["text"]
            if not isinstance(text, str):
                raise ValueError("invalid hover text")
            return text

        call = asyncio.create_task(
            adapter.invoke_read_only_facet(
                grant=grant,
                request={"symbol": "review"},
                decode_result=decode,
            )
        )
        await transport.wait_for_writes(3)
        invocation = transport.message(2)
        assert invocation.to_dict()["payload"] == {
            "admissionFingerprint": admission.fingerprint,
            "capabilityId": "coding.hover",
            "facetGrantFingerprint": grant.fingerprint,
            "facetId": "hover",
            "operation": "invokeReadOnlyFacet",
            "queryVersion": 1,
            "request": {"symbol": "review"},
        }
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=invocation.fields["correlationId"],
                payload={"responseVersion": 1, "value": {"text": "Review symbol"}},
            )
        )
        assert await call == "Review symbol"

        foreign = CapabilityWorkerFacetGrantV1(
            capability_id="coding.hover",
            facet_id="documentation",
            binding_fingerprint=grant.binding_fingerprint,
            authority_fingerprint=grant.authority_fingerprint,
            owner_policy_revision=grant.owner_policy_revision,
        )
        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await adapter.invoke_read_only_facet(
                grant=foreign,
                request={"symbol": "review"},
                decode_result=decode,
            )
        assert caught.value.code == "worker_capability_facet_grant_invalid"
        assert len(transport.writes) == 3
        with pytest.raises(CapabilityWorkerAdapterError) as oversized:
            await adapter.invoke_read_only_facet(
                grant=grant,
                request={"symbol": "x" * 20_000},
                decode_result=decode,
            )
        assert oversized.value.code == "worker_capability_facet_request_invalid"
        assert len(transport.writes) == 3
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_facet_proxy_drops_in_flight_result_after_retirement(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, _process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        admission = adapter.admit()
        describe = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        description_query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=description_query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": "coding.hover",
                            "descriptorVersion": 1,
                            "facetIds": ["hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        await describe
        grant = CapabilityWorkerFacetGrantV1(
            capability_id="coding.hover",
            facet_id="hover",
            binding_fingerprint=adapter.binding.fingerprint,
            authority_fingerprint=current[0].fingerprint,
            owner_policy_revision=current[0].owner_policy_revision,
        )
        facet = CapabilityWorkerReadOnlyFacetProxy(
            adapter=adapter,
            admission=admission,
            capability_id="coding.hover",
            facet_id="hover",
            owner_generation=3,
            graph_generation=1,
            issue_grant=lambda: (grant, lambda value: value),
        )
        facet.publish(admission=admission, owner_generation=3)
        call = asyncio.create_task(facet.invoke({"symbol": "review"}))
        await transport.wait_for_writes(3)
        invocation = transport.message(2)
        facet.retire()
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=invocation.fields["correlationId"],
                payload={"responseVersion": 1, "value": {"text": "Review symbol"}},
            )
        )
        with pytest.raises(CapabilityWorkerFacetProxyError) as retired:
            await call
        assert retired.value.code == "worker_capability_facet_proxy_retired_during_call"
        with pytest.raises(CapabilityWorkerFacetProxyError) as later:
            await facet.invoke({"symbol": "again"})
        assert later.value.code == "worker_capability_facet_proxy_not_visible"
        assert len(transport.writes) == 3
        await supervisor.fence(code="test_complete")

    asyncio.run(scenario())


def test_capability_adapter_fences_invalid_live_facet_result(tmp_path: Path) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        adapter.admit()
        describe = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        description_query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=description_query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": "coding.hover",
                            "descriptorVersion": 1,
                            "facetIds": ["hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        await describe
        grant = CapabilityWorkerFacetGrantV1(
            capability_id="coding.hover",
            facet_id="hover",
            binding_fingerprint=adapter._binding.fingerprint,
            authority_fingerprint=current[0].fingerprint,
            owner_policy_revision=current[0].owner_policy_revision,
        )
        call = asyncio.create_task(
            adapter.invoke_read_only_facet(
                grant=grant,
                request={"symbol": "review"},
                decode_result=lambda value: value["text"],
            )
        )
        await transport.wait_for_writes(3)
        invocation = transport.message(2)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=invocation.fields["correlationId"],
                payload={"responseVersion": 1, "value": {"wrong": True}},
            )
        )
        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await call
        assert caught.value.code == "worker_capability_facet_result_invalid"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_adapter_discards_facet_result_after_owner_revocation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        adapter.admit()
        describe = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        description_query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=description_query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": "coding.hover",
                            "descriptorVersion": 1,
                            "facetIds": ["hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        await describe
        grant = CapabilityWorkerFacetGrantV1(
            capability_id="coding.hover",
            facet_id="hover",
            binding_fingerprint=adapter._binding.fingerprint,
            authority_fingerprint=current[0].fingerprint,
            owner_policy_revision=current[0].owner_policy_revision,
        )
        call = asyncio.create_task(
            adapter.invoke_read_only_facet(
                grant=grant,
                request={"symbol": "review"},
                decode_result=lambda value: value["text"],
            )
        )
        await transport.wait_for_writes(3)
        invocation = transport.message(2)
        current[0] = CapabilityWorkerAuthorityV1(
            plugin_revision_digest="a" * 64,
            declaration_fingerprint="b" * 64,
            owner_generation=3,
            product_policy_revision="policy-1",
            owner_policy_revision="owner-2",
            revocation_epoch=3,
        )
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=invocation.fields["correlationId"],
                payload={"responseVersion": 1, "value": {"text": "stale result"}},
            )
        )
        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await call
        assert caught.value.code == "worker_capability_authority_stale"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_adapter_discards_result_when_authority_changes_mid_request(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        adapter.admit()
        task = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        query = transport.message(1)
        current[0] = CapabilityWorkerAuthorityV1(
            plugin_revision_digest="a" * 64,
            declaration_fingerprint="b" * 64,
            owner_generation=3,
            product_policy_revision="policy-2",
            owner_policy_revision="owner-1",
            revocation_epoch=2,
        )
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={"capabilities": [], "responseVersion": 1},
            )
        )

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await task
        assert caught.value.code == "worker_capability_authority_stale"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_adapter_fences_revocation_before_sending_a_query(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        current = [_authority()]
        adapter = _adapter(supervisor, current)
        adapter.admit()
        current[0] = CapabilityWorkerAuthorityV1(
            plugin_revision_digest="a" * 64,
            declaration_fingerprint="b" * 64,
            owner_generation=3,
            product_policy_revision="policy-1",
            owner_policy_revision="owner-1",
            revocation_epoch=3,
        )

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await adapter.describe()
        assert caught.value.code == "worker_capability_authority_stale"
        assert len(transport.writes) == 1
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_adapter_rejects_effectful_or_unknown_worker_payload(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        adapter = _adapter(supervisor, [_authority()])
        adapter.admit()
        task = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={
                    "capabilities": [],
                    "factory": "plugin.py:create",
                    "responseVersion": 1,
                },
            )
        )

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await task
        assert caught.value.code == "worker_capability_payload_invalid"
        assert supervisor.status.state == "fenced"
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_adapter_fences_result_when_authority_reader_fails(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        available = True

        def read_authority() -> CapabilityWorkerAuthorityV1:
            if not available:
                raise OSError("authority store unavailable")
            return _authority()

        adapter = bind_capability_query_worker_adapter(
            supervisor=supervisor,
            binding=_domain_binding(),
            authority_reader=read_authority,
            enabled=True,
        )
        adapter.admit()
        task = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        query = transport.message(1)
        available = False
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={"capabilities": [], "responseVersion": 1},
            )
        )

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await task
        assert caught.value.code == "worker_capability_authority_unavailable"
        assert supervisor.status.failure_code == (
            "worker_capability_authority_unavailable"
        )
        assert process.terminated is True

    asyncio.run(scenario())


def test_capability_binding_and_descriptors_enforce_collection_bounds() -> None:
    with pytest.raises(ValueError, match="allowlist exceeds"):
        CapabilityWorkerBindingV1(
            plugin_id="review-pack",
            contribution_id="review-provider",
            product_id="coding",
            scope_id="workspace:" + "a" * 64,
            owner_id="coding.lsp",
            allowed_capability_ids=tuple(
                f"coding.capability-{ordinal:03d}" for ordinal in range(129)
            ),
            authority=_authority(),
        )


def test_capability_decoder_rejects_boolean_response_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        supervisor, transport, process = await _healthy_supervisor(tmp_path)
        adapter = _adapter(supervisor, [_authority()])
        adapter.admit()
        task = asyncio.create_task(adapter.describe())
        await transport.wait_for_writes(2)
        query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={"capabilities": [], "responseVersion": True},
            )
        )

        with pytest.raises(CapabilityWorkerAdapterError) as caught:
            await task
        assert caught.value.code == "worker_capability_payload_invalid"
        assert process.terminated is True

    asyncio.run(scenario())
