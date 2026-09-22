from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from loushang.harness.session.agent_product import AgentProductSession
from loushang.harness.session.output_artifacts import SessionOutputPersistingExecService


class OutputOwner(SessionOutputPersistingExecService):
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0
        self.fenced = False

    def fence(self):
        self.fenced = True

    async def close(self):
        assert self.fenced
        self.calls += 1
        if self.fail:
            raise OSError("original cleanup debt")


def test_product_shutdown_closes_shared_output_adapter_only_once():
    async def run():
        owner = OutputOwner()
        product = SimpleNamespace(_exec_service=owner, _tool_exec_service=owner)
        await AgentProductSession._close_output_captures(product)
        assert owner.calls == 1
    asyncio.run(run())


def test_product_shutdown_tries_both_original_owners_and_can_retry():
    async def run():
        command, tool = OutputOwner(fail=True), OutputOwner()
        product = SimpleNamespace(_exec_service=command, _tool_exec_service=tool)
        with pytest.raises(OSError, match="original cleanup debt"):
            await AgentProductSession._close_output_captures(product)
        assert command.calls == tool.calls == 1
        assert product._exec_service is command
        assert product._tool_exec_service is tool
        command.fail = False
        await AgentProductSession._close_output_captures(product)
        assert command.calls == tool.calls == 2
    asyncio.run(run())


def test_output_debt_stops_disposal_before_graph_or_transcript_access():
    async def run():
        calls = []

        async def failed_close():
            calls.append("capture")
            raise OSError("capture cleanup pending")

        async def base_dispose():
            raise AssertionError("writer must remain owned")

        # Deliberately has no graph, side-question or model-call state: capture
        # must settle before disposal can even access those downstream owners.
        product = SimpleNamespace(
            _close_output_captures=failed_close,
            _fence_output_captures=lambda: None,
            _side_question_consumer=None,
        )
        with pytest.raises(OSError, match="capture cleanup pending"):
            await AgentProductSession._dispose_owned_model_call_runtime(
                product, base_dispose=base_dispose,
            )
        assert calls == ["capture"]
    asyncio.run(run())


def test_side_question_is_cancelled_before_capture_drain():
    async def run():
        calls = []
        stopped = asyncio.Event()

        async def cancel_and_wait():
            calls.append("cancel producer")
            stopped.set()

        async def close_outputs():
            assert stopped.is_set(), "capture drain must not precede producer cancellation"
            calls.append("capture drain")
            raise OSError("stop before graph")

        async def base_dispose():
            raise AssertionError("not reached")

        product = SimpleNamespace(
            _fence_output_captures=lambda: calls.append("fence"),
            _side_question_consumer=SimpleNamespace(cancel_and_wait=cancel_and_wait),
            _close_output_captures=close_outputs,
        )
        with pytest.raises(OSError, match="stop before graph"):
            await AgentProductSession._dispose_owned_model_call_runtime(product, base_dispose=base_dispose)
        assert calls == ["fence", "cancel producer", "capture drain"]
    asyncio.run(run())


def test_queued_prepare_rechecks_retirement_after_lock_acquisition():
    async def run():
        product = object.__new__(AgentProductSession)
        product._model_call_consumer = None
        product._model_call_bind_lock = asyncio.Lock()
        await product._model_call_bind_lock.acquire()
        queued = asyncio.create_task(product._ensure_session_graph_prepared())
        await asyncio.sleep(0)
        assert not queued.done()
        # The predecessor failed before it obtained any Graph/components; the
        # retirement latch, not those later fields, must reject the queued call.
        product._execution_preparation_failed = True
        product._model_call_bind_lock.release()
        with pytest.raises(RuntimeError, match="requires Session retirement"):
            await queued
    asyncio.run(run())
