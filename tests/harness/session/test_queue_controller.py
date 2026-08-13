from __future__ import annotations

from types import SimpleNamespace

from loushang.agent import Agent
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.session import QueueController


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="done")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _preflight(text: str):
    return SimpleNamespace(consumed=False, text=text)


def test_queue_controller_owns_steering_follow_up_and_next_turn_messages() -> None:
    agent = Agent()
    updates: list[tuple[list[str], list[str]]] = []
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: updates.append(
            (controller.get_steering_messages(), controller.get_follow_up_messages())
        ),
    )

    controller.steer("first")
    controller.follow_up("later")
    controller.queue_mailbox_message("system")
    controller.append_next_turn_message("next")

    assert agent.steering_queue._messages[0].timestamp == 0.0
    assert agent.follow_up_queue._messages[0].timestamp == 0.0
    assert agent.mailbox_queue._messages == ["system"]
    assert controller.get_steering_messages() == ["first"]
    assert controller.get_follow_up_messages() == ["later"]
    assert controller.drain_next_turn_messages() == ["next"]
    assert controller.drain_next_turn_messages() == []
    assert updates == [(["first"], []), (["first"], ["later"])]
    assert agent.has_queued_messages() is True


def test_queue_controller_drains_local_queue_before_continue_from_assistant() -> None:
    agent = Agent()
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )
    agent.state.messages.append(_assistant_message())
    controller.steer("first")
    controller.steer("second")

    consumed = controller.prepare_continue_run()

    assert consumed is True
    assert controller.get_steering_messages() == ["second"]
    assert controller.get_follow_up_messages() == []


def test_queue_controller_consumes_visible_queue_when_user_message_starts() -> None:
    agent = Agent()
    updates: list[tuple[list[str], list[str]]] = []
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: updates.append(
            (controller.get_steering_messages(), controller.get_follow_up_messages())
        ),
    )
    controller.steer("first")
    controller.follow_up("later")

    consumed = controller.mark_message_consumed(
        UserMessage(
            role="user", content=[TextPart(type="text", text="first")], timestamp=0.0
        )
    )

    assert consumed is True
    assert controller.get_steering_messages() == []
    assert controller.get_follow_up_messages() == ["later"]
    assert updates[-1] == ([], ["later"])


def test_queue_controller_consumes_one_matching_duplicate_at_a_time() -> None:
    agent = Agent()
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )
    controller.steer("same")
    controller.steer("same")

    consumed = controller.mark_message_consumed(
        UserMessage(
            role="user", content=[TextPart(type="text", text="same")], timestamp=0.0
        )
    )

    assert consumed is True
    assert controller.get_steering_messages() == ["same"]


def test_queue_controller_consumes_duplicate_by_message_identity_before_text() -> None:
    agent = Agent()
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )
    controller.steer("same")
    controller.steer("same")
    first_id, second_id = [item.id for item in controller.get_queue_snapshot().steering]

    consumed = controller.mark_message_consumed(agent.steering_queue._messages[1])

    assert consumed is True
    assert [item.id for item in controller.get_queue_snapshot().steering] == [first_id]
    assert first_id != second_id


def test_queue_controller_leaves_visible_queue_when_started_message_does_not_match() -> (
    None
):
    agent = Agent()
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )
    controller.steer("queued")

    consumed = controller.mark_message_consumed(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="different")],
            timestamp=0.0,
        )
    )

    assert consumed is False
    assert controller.get_steering_messages() == ["queued"]


def test_queue_controller_debug_events_for_queue_consume_and_clear(monkeypatch) -> None:
    from loushang.harness.session import queue_controller as queue_module

    events: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        queue_module,
        "log",
        SimpleNamespace(
            debug_event=lambda scope, name, **data: events.append((scope, name, data))
        ),
    )
    agent = Agent()
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )

    controller.steer("first")
    queued_id = controller.get_queue_snapshot().steering[0].id
    controller.mark_message_consumed(agent.steering_queue._messages[0])
    controller.follow_up("later")
    controller.clear_queue()

    assert (
        "agent",
        "queue.message_queued",
        {"id": queued_id, "kind": "steering", "text_len": 5},
    ) in events
    assert (
        "agent",
        "queue.message_consumed",
        {"id": queued_id, "kind": "steering", "text_len": 5},
    ) in events
    assert any(
        name == "queue.cleared" and data["steering"] == 0 and data["follow_up"] == 1
        for _scope, name, data in events
    )
