from __future__ import annotations

import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.tools.execution import AuthorizedExecution

from ._lmux_synthetic_product import components, run_product


def test_history_stream_works_in_fixed_child_run_path_context():
    from ._lmux_history_recipe import history_turn

    namespace = runpy.run_path(str(Path(__file__).with_name("_lmux_synthetic_product.py")))
    assert not namespace["__package__"]

    async def check():
        model, stream, _ = namespace["components"](lambda *_: None)
        for index in (0, 127):
            request, expected = history_turn(index)
            response = await stream(model, context(request))
            try:
                message = await response.result()
                assert message.content[0].text == expected
            finally:
                await response.aclose()

    asyncio.run(check())


def context(text, role="user"):
    return SimpleNamespace(messages=[SimpleNamespace(role=role, content=text)])


def test_unique_reply_is_bound_to_the_current_request():
    async def check():
        model, stream, _ = components(lambda *_: None)
        for token in ("a" * 32, "b" * 32):
            response = await stream(model, context("reply " + token))
            try:
                message = await response.result()
                assert message.content[0].text == "LMUX_REPLY_" + token
            finally:
                await response.aclose()

    asyncio.run(check())


def test_complete_streamed_text_does_not_supply_a_final_message():
    async def check():
        model, stream, _ = components(lambda *_: None)
        response = await stream(model, context("delayed " + "a" * 32))
        try:
            events = response.__aiter__()
            assert (await anext(events))["type"] == "start"
            delta = await anext(events)
            assert delta["type"] == "text_delta" and delta["delta"] == "LMUX_REPLY_" + "a" * 32
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(response.result(), timeout=0.02)
        finally:
            await response.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True])
def test_gated_original_producer_finishes_only_after_release(cancel):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        events = []
        token = "c" * 32

        async def gate(actual):
            assert actual == token
            started.set()
            await release.wait()

        model, stream, _ = components(lambda *row: events.append(row), completion_gate=gate)
        response = await stream(model, context("gated " + token))
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert events == [("producer_started", "lmux-call-1")]
            if cancel:
                await response.aclose()
            else:
                release.set()
                message = await asyncio.wait_for(response.result(), 1)
                assert message.content[0].text == "LMUX_REPLY_" + token
        finally:
            await response.aclose()
        expected = [("producer_started", "lmux-call-1")]
        if not cancel:
            expected += [("gate_released", "lmux-call-1"), ("final_emitted", "lmux-call-1")]
        assert events == [*expected, ("producer_settled", "lmux-call-1")]

    asyncio.run(check())


def test_gated_request_does_not_fall_back_without_explicit_test_gate():
    async def check():
        model, stream, _ = components(lambda *_: None)
        with pytest.raises(ValueError, match="explicit completion gate"):
            await stream(model, context("gated " + "d" * 32))
    asyncio.run(check())


def test_synthetic_requests_do_not_execute_authorized_tool():
    async def check():
        events = []
        model, stream, tools = components(lambda *event: events.append(event))
        assert isinstance(tools[0].execution, AuthorizedExecution)
        identifiers = []
        for _ in range(2):
            response = await stream(model, context("approval"))
            try:
                message = await response.result()
                assert message.stop_reason == "toolUse"
                identifiers.append(message.content[0].id)
            finally:
                await response.aclose()
        assert len(set(identifiers)) == 2
        assert events == []  # Generation is not approval or execution.

    asyncio.run(check())


@pytest.mark.parametrize("failure", [None, RuntimeError("construction"), KeyboardInterrupt()])
def test_product_composition_preserves_launch_capture_and_restores_name(monkeypatch, failure):
    from loushang.coding import managed_local, managed_process

    launch, capture = object(), object()
    arguments = ["original-invocation", "original-session-root", "original-descriptor"]
    seen = []

    def original(selected, **kwargs):
        assert selected is launch
        assert kwargs["output_capture_factory"] is capture
        assert set(kwargs) == {"model", "stream_fn", "tools", "output_capture_factory"}
        seen.append(kwargs)
        if failure is not None:
            raise failure
        return object()

    def entry(argv):
        assert argv is arguments
        managed_local.CodingManagedLocalCommandV1(launch, output_capture_factory=capture)
        return 7

    monkeypatch.setattr(managed_local, "CodingManagedLocalCommandV1", original)
    monkeypatch.setattr(managed_process, "main", entry)
    if failure is None:
        assert run_product(arguments, lambda *_: None) == 7
    else:
        with pytest.raises(type(failure)) as caught:
            run_product(arguments, lambda *_: None)
        assert caught.value is failure
    assert len(seen) == 1
    assert managed_local.CodingManagedLocalCommandV1 is original


@pytest.mark.parametrize("failure", [None, OSError("construction failed"), KeyboardInterrupt()])
def test_diagnostic_constructor_preserves_launch_capture_and_original_entry(monkeypatch, failure):
    from dataclasses import dataclass, replace

    from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
    from loushang.coding import managed_local, managed_process

    @dataclass(frozen=True)
    class Launch:
        managed_mux: object
        retained: object

    owner, request, capture = object(), object(), object()
    calls, records = [], []

    def prepare(value):
        assert value is request
        calls.append("prepare")
        return owner

    binding = ManagedMuxServiceBindingV1("coding.default", "a" * 64, "b" * 32, prepare)
    launch = Launch(binding, object())

    def original(selected, **kwargs):
        assert replace(selected, managed_mux=binding) == launch
        assert selected.retained is launch.retained
        assert kwargs["output_capture_factory"] is capture
        calls.append("construct")
        if failure is not None:
            raise failure
        proxy = selected.managed_mux.prepare(request)
        assert proxy.owner is owner
        return object()

    def entry(argv):
        assert argv == ["original"]
        managed_local.CodingManagedLocalCommandV1(launch, output_capture_factory=capture)
        return 9

    monkeypatch.setattr(managed_local, "CodingManagedLocalCommandV1", original)
    monkeypatch.setattr(managed_process, "main", entry)
    options = {"admission_diagnostic": lambda phase, **fields: records.append((phase, fields))}
    if failure is None:
        assert run_product(["original"], lambda *_: None, **options) == 9
        assert calls == ["construct", "prepare"]
        assert [phase for phase, fields in records] == ["admission_prepare_enter", "admission_prepare_return"]
    else:
        with pytest.raises(type(failure)) as caught:
            run_product(["original"], lambda *_: None, **options)
        assert caught.value is failure and calls == ["construct"]
    assert launch.managed_mux is binding and binding.prepare is prepare
    assert managed_local.CodingManagedLocalCommandV1 is original


def test_synthetic_model_echo_is_not_an_execution_witness():
    async def check():
        events = []
        model, stream, _ = components(lambda *event: events.append(event))
        response = await stream(model, context("LMUX_TOOL_COMPLETED", "toolResult"))
        try:
            message = await response.result()
            assert message.content[0].text == "LMUX_TOOL_COMPLETED"
            assert events == []
        finally:
            await response.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("factory_fault", [None, "before", "after"])
def test_held_producer_witness_is_emitted_only_after_actual_settlement(factory_fault):
    async def check():
        events = []
        started = asyncio.Event()

        def witness(kind, identity):
            events.append((kind, identity))
            if kind == "producer_started":
                started.set()

        model, stream, _ = components(witness)
        loop = asyncio.get_running_loop()
        original_factory = loop.get_task_factory()
        factory_calls, factory_tasks = [], []

        def broken_factory(loop, coroutine, **kwargs):
            factory_calls.append(factory_fault)
            if factory_fault == "after":
                factory_tasks.append(asyncio.Task(coroutine, loop=loop, **kwargs))
            else:
                coroutine.close()
            raise RuntimeError("foreign task factory failed")

        try:
            if factory_fault is not None:
                loop.set_task_factory(broken_factory)
            try:
                response = await stream(model, context("hold"))
            finally:
                loop.set_task_factory(original_factory)
        finally:
            for task in factory_tasks:
                task.cancel()
            if factory_tasks:
                await asyncio.gather(*factory_tasks, return_exceptions=True)
        try:
            assert factory_calls == []
            await asyncio.wait_for(started.wait(), timeout=2)
            assert events == [("producer_started", "lmux-call-1")]
        finally:
            await response.aclose()
        assert events == [
            ("producer_started", "lmux-call-1"), ("producer_settled", "lmux-call-1"),
        ]

    asyncio.run(check())
