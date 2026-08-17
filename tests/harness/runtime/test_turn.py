from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.runtime.turn import TurnInput, TurnInputQueue, TurnOrchestrator


def test_turn_orchestrator_runs_neutral_pipeline_in_order() -> None:
    order: list[str] = []
    accepted: list[bool] = []

    async def intercept(item: TurnInput[tuple[str, ...]]) -> TurnInput[tuple[str, ...]]:
        order.append("intercept")
        return TurnInput(
            text=f"{item.text}:i", attachments=item.attachments, source=item.source
        )

    async def preflight(item: TurnInput[tuple[str, ...]]) -> TurnInput[tuple[str, ...]]:
        order.append("preflight")
        return TurnInput(
            text=f"{item.text}:p", attachments=item.attachments, source=item.source
        )

    async def before_run() -> None:
        order.append("before_run")

    async def before_start(item: TurnInput[tuple[str, ...]]) -> list[str]:
        order.append(f"before_start:{item.text}")
        return ["extension"]

    async def run(messages: list[str]) -> None:
        order.append(f"run:{','.join(messages)}")

    orchestrator: TurnOrchestrator[tuple[str, ...], str] = TurnOrchestrator(
        interceptors=(intercept,),
        preflight=preflight,
        is_running=lambda: False,
        queue_turn=lambda kind, item: None,
        build_message=lambda item: item.text,
        drain_pending=lambda: ["pending"],
        before_run=before_run,
        before_start=before_start,
        run_turn=run,
    )

    asyncio.run(
        orchestrator.run(
            TurnInput(text="prompt", attachments=("image",)),
            report_accepted=accepted.append,
        )
    )

    assert order == [
        "intercept",
        "preflight",
        "before_run",
        "before_start:prompt:i:p",
        "run:prompt:i:p,pending,extension",
    ]
    assert accepted == [True]


def test_turn_orchestrator_queues_active_turn_and_reports_rejection() -> None:
    queued: list[tuple[str, str]] = []
    accepted: list[bool] = []

    async def preflight(item: TurnInput[None]) -> TurnInput[None]:
        return item

    orchestrator: TurnOrchestrator[None, str] = TurnOrchestrator(
        preflight=preflight,
        is_running=lambda: True,
        queue_turn=lambda kind, item: queued.append((kind, item.text)),
        build_message=lambda item: item.text,
        drain_pending=list,
        run_turn=lambda messages: _noop(),
    )

    asyncio.run(
        orchestrator.run(
            TurnInput(text="later"),
            streaming_behavior="followUp",
            report_accepted=accepted.append,
        )
    )
    assert queued == [("follow_up", "later")]
    assert accepted == [True]

    with pytest.raises(RuntimeError, match="already processing"):
        asyncio.run(
            orchestrator.run(
                TurnInput(text="rejected"),
                report_accepted=accepted.append,
            )
        )
    assert accepted == [True, False]


@dataclass(frozen=True)
class Payload:
    text: str


def test_turn_input_queue_coordinates_delivery_visibility_and_continue() -> None:
    delivered: list[tuple[str, Payload]] = []
    notifications: list[str] = []
    queue: TurnInputQueue[Payload] = TurnInputQueue(
        submit=lambda kind, payload: _submit(delivered, kind, payload),
        clear_delivery_queue=lambda: delivered.clear(),
        has_delivery_messages=lambda: bool(delivered),
        notify=lambda: notifications.append("changed"),
    )
    first = Payload("first")
    queue.enqueue("steering", text="first", payload=first)
    queue.enqueue("follow_up", text="later", payload=Payload("later"))

    assert queue.has_pending() is True
    assert queue.consume_visible(first, fallback_text="first") is True
    assert (
        queue.prepare_continue(
            previous_turn_completed=True,
            steering_mode="one-at-a-time",
            follow_up_mode="one-at-a-time",
        )
        is True
    )
    assert queue.texts("follow_up") == []
    previous = queue.clear()

    assert [item.text for item in previous.steering] == []
    assert delivered == []
    assert notifications == ["changed", "changed", "changed", "changed"]


def _submit(values: list[tuple[str, Payload]], kind: str, payload: Payload) -> Payload:
    values.append((kind, payload))
    return payload


async def _noop() -> None:
    return None
