"""Deterministic real-Product boundaries; no terminal or live model dependency."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from unittest.mock import patch

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.types import TextPart
from loushang.appserver.protocol import AppServiceError, SessionEventKindV1
from loushang.coding.appservice_adapter import CodingHostedSessionV1
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1

from .test_hosted_execution import _binding, _message
from .test_hosted_legacy_evidence import _private_environment as _isolated_environment


@pytest.fixture(autouse=True)
def _private_environment(tmp_path):
    with patch.dict(os.environ, _isolated_environment(tmp_path), clear=True):
        yield


@pytest.mark.parametrize("execution", [False, True], ids=["legacy", "execution"])
def test_reply_is_not_admission_but_completed_call_preserves_second_input(
    tmp_path, execution
):
    async def scenario():
        release = [asyncio.Event(), asyncio.Event()]
        reply_seen = asyncio.Event()
        second_entered = asyncio.Event()
        inputs = []
        phases = []

        @synthetic_model_transport
        async def model(_model, context, options=None):
            index = len(inputs)
            latest = context.messages[-1]
            content = latest.content
            text = (
                content
                if isinstance(content, str)
                else "".join(
                    part.text for part in content if isinstance(part, TextPart)
                )
            )
            inputs.append((latest.role, text))
            phases.append(f"model-{index + 1}")
            if index == 1:
                second_entered.set()
            message = replace(_message(), content=[TextPart(type="text", text="reply")])
            stream = AssistantMessageEventStream()
            stream.push({"type": "start", "partial": message})
            stream.push(
                {
                    "type": "text_delta",
                    "content_index": 0,
                    "delta": "reply",
                    "partial": message,
                }
            )

            async def producer():
                await release[index].wait()
                phases.append(f"producer-{index + 1}-finished")
                stream.push({"type": "done", "reason": "stop", "message": message})

            stream.attach_task(asyncio.create_task(producer()))
            return stream

        binding, _session = await _binding(tmp_path, stream_fn=model)
        hosted = (
            CodingHostedExecutionSessionV1(binding)
            if execution
            else CodingHostedSessionV1(binding)
        )

        async def observe(event):
            if event.kind is SessionEventKindV1.ASSISTANT_DELTA:
                reply_seen.set()

        unsubscribe = hosted.subscribe(observe)
        tasks = []
        try:
            first = asyncio.create_task(hosted.start_turn("first"))
            tasks.append(first)
            await reply_seen.wait()
            assert not first.done()
            assert (await hosted.snapshot()).running
            with pytest.raises((RuntimeError, AppServiceError)):
                await hosted.start_turn("hold")
            assert inputs == [("user", "first")]
            release[0].set()
            await first
            phases.append("first-call-returned")
            second = asyncio.create_task(hosted.start_turn("hold"))
            tasks.append(second)
            await second_entered.wait()
            assert inputs == [("user", "first"), ("user", "hold")]
            assert phases.index("first-call-returned") < phases.index("model-2")
            release[1].set()
            await second
            assert not (await hosted.snapshot()).running
        finally:
            for event in release:
                event.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            unsubscribe()
            await hosted.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))


@pytest.mark.parametrize("execution", [False, True], ids=["legacy", "execution"])
def test_completed_projection_does_not_release_service_admission(tmp_path, execution):
    from loushang.appserver.protocol import (
        AppErrorCodeV1,
        MuxCreateV1,
        MuxSelectorV1,
        SessionOpenSpecV1,
    )
    from loushang.appservice.client_scope import ScopedAppServiceV1
    from loushang.appservice.runtime import AppServiceV1
    from loushang.coding.hosted_execution import create_coding_execution_service_binding
    from loushang.harnesstui.mux.profile import open_hosted_mux_profile

    async def scenario():
        completed, release = asyncio.Event(), asyncio.Event()
        inputs = []

        @synthetic_model_transport
        async def model(_model, context, options=None):
            latest = context.messages[-1]
            content = latest.content
            text = (
                content
                if isinstance(content, str)
                else "".join(
                    part.text for part in content if isinstance(part, TextPart)
                )
            )
            inputs.append((latest.role, text))
            stream = AssistantMessageEventStream()
            stream.push({"type": "done", "reason": "stop", "message": _message()})
            return stream

        binding, _ = await _binding(tmp_path, stream_fn=model)
        hosted = (
            CodingHostedExecutionSessionV1(binding)
            if execution
            else CodingHostedSessionV1(binding)
        )

        async def observe(event):
            if event.kind is SessionEventKindV1.TURN_COMPLETED:
                completed.set()
                await release.wait()

        unsubscribe = hosted.subscribe(observe)

        class Resolver:
            async def open_session(self, request):
                return hosted

        service = AppServiceV1(
            product_id="coding",
            resolver=Resolver(),
            execution=(
                create_coding_execution_service_binding(
                    "application",
                    service_instance_id="instance",
                )
                if execution
                else None
            ),
        )
        owner = ScopedAppServiceV1(service)
        scope = owner.open_client_scope()
        first = None
        try:
            await scope.create_mux(MuxCreateV1("dev"))
            controller = await open_hosted_mux_profile(
                scope, selector=MuxSelectorV1(name="dev")
            )
            identity = binding.identity
            await controller.open_member(
                SessionOpenSpecV1(
                    identity.product_id,
                    identity.continuity_id,
                    identity.scope,
                    identity.scope_fingerprint,
                    "Boundary",
                    identity.session_id,
                )
            )
            first = asyncio.create_task(controller.submit("first"))
            await completed.wait()
            assert not first.done()
            assert (await hosted.snapshot()).running
            with pytest.raises(AppServiceError) as rejected:
                await controller.submit("hold")
            assert rejected.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
            assert inputs == [("user", "first")]
            release.set()
            await first
            await controller.submit("hold")
            assert inputs == [("user", "first"), ("user", "hold")]
            assert not (await hosted.snapshot()).running
            await controller.close()
        finally:
            release.set()
            if first is not None:
                await asyncio.gather(first, return_exceptions=True)
            unsubscribe()
            await owner.close()

    asyncio.run(asyncio.wait_for(scenario(), 20))
