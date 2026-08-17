from __future__ import annotations


def test_event_matcher_supports_type_and_contains() -> None:
    from loushang.harness.scenario.events import (
        EventPattern,
        WorkflowEvent,
        event_matches,
    )

    event = WorkflowEvent(type="assistant.message", text="你好，已完成", data={})

    assert event_matches(
        event, EventPattern(event="assistant.message", contains="你好")
    )
    assert not event_matches(
        event, EventPattern(event="assistant.message", contains="旧任务")
    )


def test_event_matcher_supports_shallow_data_match() -> None:
    from loushang.harness.scenario.events import (
        EventPattern,
        WorkflowEvent,
        event_matches,
    )

    event = WorkflowEvent(
        type="queue.steer_added", data={"queue": "steering", "size": 1}
    )

    assert event_matches(
        event, EventPattern(event="queue.steer_added", data={"queue": "steering"})
    )
    assert not event_matches(
        event, EventPattern(event="queue.steer_added", data={"queue": "follow_up"})
    )
