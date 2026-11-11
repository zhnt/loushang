"""The existing Supervisor uses rooted Product history through cleanup and reopen."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_supervisor_journal import (
    CodingProductWorkerSupervisorJournal,
)
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    WorkerFramedTransport,
    WorkerProtocolMessage,
    WorkerSupervisor,
)
from loushang.harness.worker.journal import WorkerSupervisorJournalError
from loushang.harness.worker.supervisor import WorkerSupervisorError
from tests.coding.test_package_product_worker_supervisor_segments import _product
from tests.harness.worker.test_supervisor import (
    _identity,
    _LaunchPort,
    _Process,
    _ready,
    _runtime,
    _ScriptedByteTransport,
)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Product profile")
def test_rooted_supervisor_reopens_cleanup_debt_before_allowing_next_attempt(
    tmp_path: Path,
) -> None:
    class TreeProcess(_Process):
        allow_close = False

        async def close(self) -> None:
            if not self.allow_close:
                raise RuntimeError("tree still active")
            await super().close()

    owner = _product(tmp_path)

    async def scenario() -> None:
        product = owner.runtime_owner.product_owner
        runtime = _runtime(tmp_path)
        identity = replace(_identity(runtime), scope_id=product.policy.project_scope_id)
        journal = CodingProductWorkerSupervisorJournal(product)
        process = TreeProcess()
        transport = _ScriptedByteTransport()
        transport.feed(_ready(identity))
        supervisor = WorkerSupervisor(
            identity=identity,
            journal=journal,
            protocol="capability.query",
            protocol_version=1,
        )
        await supervisor.start(
            launch_port=_LaunchPort(process),  # type: ignore[arg-type]
            launch_request=ManagedWorkerLaunchRequestV1(
                identity=identity, runtime=runtime, validate_current=lambda: None
            ),
            transport=WorkerFramedTransport(transport),
            correlation_id="rooted-launch",
        )
        shutdown = asyncio.create_task(supervisor.shutdown())
        await transport.wait_for_writes(2)
        transport.feed(WorkerProtocolMessage.create("shutdown_ack"))
        process.finish(0)
        with pytest.raises(WorkerSupervisorError, match="shutdown"):
            await shutdown
        reopened = CodingProductWorkerSupervisorJournal(product)
        failed = reopened.status(identity.attempt_id)
        assert failed is not None and failed.phase == "fenced"
        assert not failed.process_settled
        successor = replace(identity, attempt_id="e" * 32, supervisor_epoch=2)
        with pytest.raises(WorkerSupervisorJournalError) as blocked:
            reopened.claim(successor, max_attempts=3)
        assert blocked.value.code == "worker_prior_attempt_unsettled"
        with pytest.raises(WorkerSupervisorError) as still_active:
            await supervisor.settle_failed_process()
        assert still_active.value.code == "worker_process_settlement_unavailable"
        assert reopened.status(identity.attempt_id) == failed
        process.allow_close = True
        await supervisor.settle_failed_process()
        settled = reopened.status(identity.attempt_id)
        assert settled is not None and settled.phase == "process_settled"
        assert reopened.next_supervisor_epoch(successor) == 2
        claimed = reopened.claim(successor, max_attempts=3)
        assert claimed.restart_ordinal == 2
        assert (
            CodingProductWorkerSupervisorJournal(product).status(successor.attempt_id)
            == claimed
        )

    try:
        asyncio.run(scenario())
    finally:
        owner.close()
