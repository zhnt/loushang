"""Offline framed IPC and native terminal evidence using private Product roots."""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import pytest

from loushang.appserver.protocol import (
    MuxCreateV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.coding.cli.hosted import parse_launch
from loushang.harnesstui.mux.profile import open_hosted_mux_profile

from ._hosted_boundary_trace import MAX_RECORD_BYTES, MAX_RECORDS, TRACE_ENV, text_shape
from .test_hosted_legacy_evidence import _private_environment
from .test_hosted_subprocess import _argv, _child
from .test_mux_product_terminal import (
    test_G16_PRODUCT_TERMINAL_process_death_recovers_history_not_execution as _crash,
)


def _environment(root):
    trace = root / "boundary-trace"
    trace.mkdir(mode=0o700)
    return {**_private_environment(root), TRACE_ENV: str(trace)}


def _records(root):
    paths = tuple((root / "boundary-trace").glob("boundary-*.jsonl"))
    assert paths, "child must produce bounded diagnostic evidence"
    records = []
    for path in paths:
        assert path.stat().st_size <= MAX_RECORD_BYTES * MAX_RECORDS
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(rows) < MAX_RECORDS, "saturated trace is not complete boundary evidence"
        assert [row["sequence"] for row in rows] == list(range(len(rows)))
        records.extend(rows)
    return records


def _assert_inputs(records, expected):
    models = [row for row in records if row["phase"] == "model_input"]
    assert len(models) == len(expected), records
    for model, text in zip(models, expected, strict=True):
        assert model["latest_role"] == "user" and model["latest"] == text_shape(text), (
            records
        )
        request = model["request"]
        assert request is not None, records
        related = [row for row in records if row["request"] == request]
        assert next(row for row in related if row["phase"] == "rpc_received")[
            "input"
        ] == text_shape(text)
        assert next(row for row in related if row["phase"] == "product_entered")[
            "input"
        ] == text_shape(text)
        reply = "waiting" if text == "hold" else "真实跨进程回复\nG14"
        assert any(
            row["phase"] == "projection"
            and row["kind"] == "assistant_delta"
            and row["text"] == text_shape(reply)
            for row in related
        ), related
    return models


@pytest.mark.parametrize("scope_kind", [SessionScopeV1.CWD, SessionScopeV1.USER_HOME])
def test_boundary_framed_two_turn_interrupt_and_next_turn(tmp_path, scope_kind):
    async def scenario():
        launch, _ = parse_launch(_argv(tmp_path))
        scope = next(item for item in launch.scopes if item.scope is scope_kind)
        async with _child(tmp_path) as client:
            await client.create_mux(MuxCreateV1("dev"))
            controller = await open_hosted_mux_profile(
                client, selector=MuxSelectorV1(name="dev")
            )
            state = await controller.open_member(
                SessionOpenSpecV1(
                    "coding",
                    "boundary",
                    scope_kind,
                    scope.fingerprint,
                    "Boundary",
                )
            )
            window = state.active_window
            assert window is not None
            held = None
            try:
                await controller.submit(
                    "first"
                )  # ACK, not rendered text, is this path's fence.
                held = asyncio.create_task(controller.submit("hold"))
                while "waiting" not in window.assistant_draft:
                    await controller.poll()  # Real framed read yields to the producer.
                assert window.running and not held.done()
                await controller.interrupt()
                await held
                await controller.submit("after-interrupt")
                while window.running or not any(
                    record.text == "after-interrupt" for record in window.records
                ):
                    await controller.poll()
                assert not window.running
            finally:
                if held is not None and not held.done():
                    await controller.interrupt()
                    await held
                await controller.close()

    with patch.dict(os.environ, _environment(tmp_path), clear=True):
        asyncio.run(asyncio.wait_for(scenario(), 90))
    rows = _records(tmp_path)
    models = _assert_inputs(rows, ["first", "hold", "after-interrupt"])
    for model in models:
        phases = [row["phase"] for row in rows if row["request"] == model["request"]]
        assert (
            phases.index("agent_run_released")
            < phases.index("product_returned")
            < phases.index("rpc_returned")
        ), rows
        if model["latest"]["exact_hold"]:
            assert phases.index("producer_settled") < phases.index(
                "agent_run_released"
            ), rows
    assert any(row["phase"] == "producer_settled" for row in rows)
    assert any(row["phase"] == "close_returned" for row in rows)


@pytest.mark.parametrize("scope", ["cwd", "user_home"])
def test_boundary_native_two_turn_crash_recovery(
    tmp_path, record_testsuite_property, scope
):
    with patch.dict(os.environ, _environment(tmp_path), clear=True):
        _crash(tmp_path, record_testsuite_property, scope)
    rows = _records(tmp_path)
    # Files are per process, so correlate records within a process and inputs
    # by digest, never sort unrelated process clocks to invent a global order.
    for expected in ("persisted-before-process-death", "hold", "fresh-after-restart"):
        matches = [
            row
            for row in rows
            if row["phase"] == "model_input" and row["latest"] == text_shape(expected)
        ]
        assert len(matches) == 1, rows
        model = matches[0]
        related = [row for row in rows if row["request"] == model["request"]]
        _assert_inputs(related, [expected])
        phases = [row["phase"] for row in related]
        assert phases.index("slot_admitted") < phases.index("product_entered"), related
        if expected != "hold":
            assert (
                phases.index("agent_run_released")
                < phases.index("product_returned")
                < phases.index("slot_released")
                < phases.index("rpc_returned")
            ), related
        else:
            assert "agent_run_released" not in phases, related
            assert "product_returned" not in phases, related
            assert "slot_released" not in phases, related
    assert len([row for row in rows if row["phase"] == "model_input"]) == 3, rows
