from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loushang.harness.multiagent import (
    AgentCaller,
    AgentPath,
    AgentTypeRegistry,
    AgentTypeSpec,
    ControlLimits,
    HostCaller,
    MultiAgentControl,
    MultiAgentError,
)

NOW = datetime(2026, 7, 26, tzinfo=UTC)
HOST = HostCaller()


def _types() -> AgentTypeRegistry:
    return AgentTypeRegistry(
        (
            AgentTypeSpec(
                name="coordinator",
                can_spawn=True,
                maximum_children=3,
            ),
            AgentTypeSpec(name="reviewer", maximum_children=3),
            AgentTypeSpec(name="explorer", maximum_children=1),
        )
    )


def _control(
    *, limits: ControlLimits | None = None, **kwargs: object
) -> MultiAgentControl:
    return MultiAgentControl(
        agent_types=_types(),
        limits=limits,
        clock=lambda: NOW,
        **kwargs,
    )


def _spawn(
    control: MultiAgentControl,
    name: str,
    agent_type: str = "reviewer",
) -> object:
    return control.spawn(
        caller=HOST,
        parent_path=AgentPath.root(),
        name=name,
        agent_type=agent_type,
    )


def _close_tree(control: MultiAgentControl, target: AgentPath) -> None:
    for record in control.plan_close_tree(caller=HOST, target=target):
        transition = control.commit_closed(record.ref)
        assert transition.applied is True


def test_default_authority_allows_parent_child_but_denies_siblings() -> None:
    control = _control()
    left = _spawn(control, "left", "coordinator")
    right = _spawn(control, "right", "coordinator")
    child = control.spawn(
        caller=AgentCaller(left.ref),
        parent_path=left.path,
        name="child",
        agent_type="reviewer",
    )

    to_parent = control.route_message(
        caller=AgentCaller(child.ref),
        target="parent",
        text="Review complete.",
    )
    to_child = control.route_message(
        caller=AgentCaller(left.ref),
        target="child",
        text="Check one more edge case.",
    )

    assert to_parent.message.recipient_ref == left.ref
    assert to_child.message.recipient_ref == child.ref
    with pytest.raises(MultiAgentError) as error:
        control.route_message(
            caller=AgentCaller(left.ref),
            target=right.path,
            text="Cross branch.",
        )
    assert error.value.code == "agent_authority_denied"
    assert [
        record.path for record in control.list_agents(caller=AgentCaller(left.ref))
    ] == [
        left.path,
        child.path,
    ]

    close_plan = control.plan_close_tree(
        caller=AgentCaller(left.ref),
        target=left.path,
    )
    assert [record.path for record in close_plan] == [child.path, left.path]
    assert control.registry.get(child.ref).status == "idle"


def test_limits_count_only_open_agents_and_close_releases_capacity() -> None:
    control = _control(limits=ControlLimits(max_open_agents=2, max_spawn_depth=2))
    first = _spawn(control, "first")

    with pytest.raises(MultiAgentError) as error:
        _spawn(control, "second")
    assert error.value.code == "agent_limit_reached"
    assert error.value.details["limit"] == 2
    assert error.value.details["open_count"] == 2
    assert [
        occupant["path"] for occupant in error.value.details["open_agents"]
    ] == ["/root", "/root/first"]
    assert error.value.tool_result_details["code"] == "agent_limit_reached"

    _close_tree(control, first.path)
    second = _spawn(control, "second")

    assert second.status == "idle"


def test_per_type_child_limit_is_released_on_close() -> None:
    types = AgentTypeRegistry((AgentTypeSpec(name="reviewer", maximum_children=1),))
    control = MultiAgentControl(agent_types=types, clock=lambda: NOW)
    first = control.spawn(
        caller=HOST,
        parent_path=AgentPath.root(),
        name="first",
        agent_type="reviewer",
    )
    started = control.begin_round(first.ref)
    assert started.record is not None
    completed = control.finish_round(
        first.ref,
        round_id=started.record.round_id,
        status="completed",
        final_message="First task complete.",
        duration_ms=1,
    )
    assert completed.record is not None

    with pytest.raises(MultiAgentError) as error:
        control.spawn(
            caller=HOST,
            parent_path=AgentPath.root(),
            name="second",
            agent_type="reviewer",
        )
    assert error.value.code == "agent_type_limit_reached"
    assert error.value.details["parent_path"] == "/root"
    assert error.value.details["open_count"] == 1
    assert error.value.details["open_children"] == (
        {
            "path": "/root/first",
            "agent_type": "reviewer",
            "status": "completed",
            "round_id": 1,
        },
    )
    assert error.value.tool_result_details == {
        "code": "agent_type_limit_reached",
        **error.value.details,
    }

    _close_tree(control, first.path)
    second = control.spawn(
        caller=HOST,
        parent_path=AgentPath.root(),
        name="second",
        agent_type="reviewer",
    )
    assert second.status == "idle"


def test_depth_limit_is_checked_before_reservation() -> None:
    control = _control(limits=ControlLimits(max_open_agents=6, max_spawn_depth=1))
    parent = _spawn(control, "parent", "coordinator")

    with pytest.raises(MultiAgentError) as error:
        control.spawn(
            caller=AgentCaller(parent.ref),
            parent_path=parent.path,
            name="too_deep",
            agent_type="reviewer",
        )

    assert error.value.code == "agent_depth_exceeded"
    assert control.registry.reserved_count == 0


def test_usage_summary_and_terminal_notice_are_round_safe() -> None:
    control = _control()
    reviewer = _spawn(control, "reviewer")
    started = control.begin_round(reviewer.ref)
    assert started.record is not None
    first_round = started.record.round_id

    control.record_progress(
        reviewer.ref,
        round_id=first_round,
        latest_input_tokens=100,
        output_tokens_delta=5,
        tool_uses_delta=1,
        recent_activity="reading",
        summary="Initial finding",
    )
    progressed = control.record_progress(
        reviewer.ref,
        round_id=first_round,
        latest_input_tokens=120,
        output_tokens_delta=7,
        recent_activity="checking tests",
    )
    assert progressed.record is not None
    assert progressed.record.progress.usage.latest_input_tokens == 120
    assert progressed.record.progress.usage.cumulative_output_tokens == 12
    assert progressed.record.progress.summary == "Initial finding"

    first = control.finish_round(
        reviewer.ref,
        round_id=first_round,
        status="completed",
        final_message="No blocker.",
        duration_ms=50,
        workspace_ref="workspace://reviewer",
        artifact_refs=("artifact://report",),
        change_set_ref="changes://review",
    )
    duplicate = control.finish_round(
        reviewer.ref,
        round_id=first_round,
        status="completed",
        final_message="Duplicate callback.",
        duration_ms=51,
    )
    second_started = control.begin_round(reviewer.ref)
    assert second_started.record is not None
    second = control.finish_round(
        reviewer.ref,
        round_id=second_started.record.round_id,
        status="completed",
        final_message="Follow-up complete.",
        duration_ms=30,
    )

    assert first.applied is True
    assert duplicate.reason == "duplicate"
    assert second.applied is True
    assert [notice.round_id for notice in control.notices()] == [1, 2]
    assert [notice.notice_id for notice in control.notices()] == [
        f"{reviewer.ref}:1",
        f"{reviewer.ref}:2",
    ]
    assert control.completion_notice(reviewer.ref, round_id=2) is second.notice
    assert control.completion_notice(reviewer.ref, round_id=3) is None
    assert first.notice is not None
    assert first.notice.workspace_ref == "workspace://reviewer"
    assert first.notice.artifact_refs == ("artifact://report",)
    assert first.notice.change_set_ref == "changes://review"
    assert first.record is not None
    assert first.record.workspace_ref == "workspace://reviewer"
    terminal_fact = next(
        fact
        for fact in control.facts()
        if fact.kind == "terminal" and fact.round_id == first_round
    )
    assert terminal_fact.workspace_ref == "workspace://reviewer"
    assert terminal_fact.artifact_refs == ("artifact://report",)


def test_stale_callback_cannot_mutate_a_reused_path() -> None:
    control = _control()
    original = _spawn(control, "reviewer")
    started = control.begin_round(original.ref)
    assert started.record is not None
    _close_tree(control, original.path)
    replacement = _spawn(control, "reviewer")

    stale = control.finish_round(
        original.ref,
        round_id=started.record.round_id,
        status="completed",
        final_message="Late result.",
        duration_ms=100,
    )

    assert stale.reason == "stale_ref"
    assert replacement.ref.incarnation == original.ref.incarnation + 1
    assert control.registry.get(replacement.ref).status == "idle"
    assert control.notices() == ()


def test_message_routing_is_a_pure_intent_and_does_not_wake_or_change_state() -> None:
    control = _control()
    reviewer = _spawn(control, "reviewer")
    started = control.begin_round(reviewer.ref)
    assert started.record is not None
    control.finish_round(
        reviewer.ref,
        round_id=started.record.round_id,
        status="completed",
        final_message="Done.",
        duration_ms=10,
    )

    intent = control.route_message(
        caller=HOST,
        target=reviewer.path,
        text="Please check one more thing.",
    )

    assert intent.requires_wake is True
    assert intent.target_status == "completed"
    assert control.registry.get(reviewer.ref).status == "completed"
    assert len(control.notices()) == 1


def test_failing_fact_and_notice_consumers_do_not_rollback_state() -> None:
    observed_facts: list[str] = []
    observed_notices: list[str] = []

    def fail(_value: object) -> None:
        raise RuntimeError("consumer failed")

    control = _control(
        fact_consumers=(fail, lambda fact: observed_facts.append(fact.kind)),
        notice_consumers=(
            fail,
            lambda notice: observed_notices.append(notice.notice_id),
        ),
    )
    reviewer = _spawn(control, "reviewer")
    started = control.begin_round(reviewer.ref)
    assert started.record is not None
    terminal = control.finish_round(
        reviewer.ref,
        round_id=started.record.round_id,
        status="completed",
        final_message="Done.",
        duration_ms=10,
    )

    assert terminal.applied is True
    assert observed_facts == ["spawned", "status_changed", "terminal"]
    assert observed_notices == [f"{reviewer.ref}:1"]


def test_live_fact_subscription_can_be_removed_without_changing_control_state() -> None:
    control = _control()
    observed: list[str] = []
    unsubscribe = control.subscribe_facts(lambda fact: observed.append(fact.kind))

    reviewer = _spawn(control, "reviewer")
    unsubscribe()
    started = control.begin_round(reviewer.ref)

    assert started.applied is True
    assert observed == ["spawned"]
    assert [fact.kind for fact in control.facts()][-2:] == [
        "spawned",
        "status_changed",
    ]
