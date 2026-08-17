from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loushang.harnesswork import InMemoryEventLogBackend
from loushang.harnesswork.integrations.session import (
    SessionWorkProfile,
    SessionWorkRuntime,
    SessionWorkTurn,
    project_prepared_session_work_turns,
    require_session_work_turn,
    submit_session_turn,
)


@dataclass(frozen=True)
class _DesignPreparedTurn:
    prepared_prompt: str
    method_id: str | None = "design-review"
    plan_id: str | None = "plan-design"
    step_id: str | None = "critique"
    step_index: int | None = 0
    step_title: str | None = "Critique layout"
    metadata: Mapping[str, object] = field(
        default_factory=lambda: {"audit_policy": {"record": ["evidence"]}}
    )


class _DesignSession:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def subscribe_runtime_events(
        self,
        listener: Callable[[object], object],
    ) -> Callable[[], None]:
        del listener
        return lambda: None

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)

    async def wait_for_idle(self) -> None:
        raise AssertionError("settled prompt must not be followed by a second wait")


def test_session_work_runtime_accepts_product_vocabulary_as_a_profile() -> None:
    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = _DesignSession()
        runtime = SessionWorkRuntime(
            session=session,
            event_log=event_log,
            profile=SessionWorkProfile(
                domain="design",
                operation_kind="SubmitDesignTurn",
            ),
            project_event_facts=lambda _event: (),
            clock=lambda: datetime(2026, 7, 23, tzinfo=UTC),
        )

        run = await runtime.submit_turn(
            SessionWorkTurn(text="revise the title slide"),
            session_id="design-session",
            operation_id="design-operation",
            run_id="design-run",
        )

        assert run.status == "completed"
        assert session.prompts == ["revise the title slide"]
        operation = event_log.query(run_id="design-run")[0]
        assert operation.payload == {
            "kind": "SubmitDesignTurn",
            "domain": "design",
            "payload": {"text": "revise the title slide"},
        }

    asyncio.run(scenario())


def test_submit_session_turn_selects_direct_or_work_delivery() -> None:
    async def scenario() -> None:
        direct_session = _DesignSession()
        direct_result = await submit_session_turn(
            direct_session,
            SessionWorkTurn(text="draft directly"),
            session_id="design-direct",
        )

        work_session = _DesignSession()
        event_log = InMemoryEventLogBackend()
        runtime = SessionWorkRuntime(
            session=work_session,
            event_log=event_log,
            profile=SessionWorkProfile(
                domain="design",
                operation_kind="SubmitDesignTurn",
            ),
            project_event_facts=lambda _event: (),
        )
        work_result = await submit_session_turn(
            work_session,
            SessionWorkTurn(text="draft with evidence"),
            session_id="design-work",
            work_runtime=lambda: runtime,
        )

        assert direct_result is None
        assert direct_session.prompts == ["draft directly"]
        assert work_result is not None
        assert work_result.status == "completed"
        assert work_session.prompts == ["draft with evidence"]
        assert event_log.query(session_id="design-work")

    asyncio.run(scenario())


def test_require_session_work_turn_rejects_product_specific_values() -> None:
    turn = SessionWorkTurn(text="review")

    assert require_session_work_turn(turn) is turn
    try:
        require_session_work_turn(object())
    except TypeError as error:
        assert str(error) == "planned execution requires SessionWorkTurn values"
    else:  # pragma: no cover - defensive
        raise AssertionError("product-specific turn should be rejected")


def test_prepared_turn_projection_is_product_neutral() -> None:
    turns = project_prepared_session_work_turns(
        (_DesignPreparedTurn("Review the first slide"),),
        images=("image",),
        follow_up_messages=("Check contrast",),
    )

    assert turns == (
        SessionWorkTurn(
            text="Review the first slide",
            images=("image",),
            method_id="design-review",
            plan_id="plan-design",
            step_id="critique",
            step_index=0,
            step_title="Critique layout",
            audit_policy={"record": ["evidence"]},
            follow_up_messages=("Check contrast",),
        ),
    )


def test_session_work_plan_waits_for_each_prompt_before_advancing() -> None:
    class BlockingPlanSession:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.first_prompt_started = asyncio.Event()
            self.release_first_prompt = asyncio.Event()

        def subscribe_runtime_events(
            self,
            listener: Callable[[object], object],
        ) -> Callable[[], None]:
            del listener
            return lambda: None

        async def prompt(
            self,
            text: str,
            *,
            images: object = None,
            streaming_behavior: str | None = None,
            source: str | None = None,
        ) -> None:
            del images, streaming_behavior, source
            self.prompts.append(text)
            if len(self.prompts) == 1:
                self.first_prompt_started.set()
                await self.release_first_prompt.wait()

        async def wait_for_idle(self) -> None:
            raise AssertionError("prompt already owns idle settlement")

    async def scenario() -> None:
        session = BlockingPlanSession()
        after_turns: list[str] = []
        runtime = SessionWorkRuntime(
            session=session,
            event_log=InMemoryEventLogBackend(),
            profile=SessionWorkProfile(
                domain="design",
                operation_kind="SubmitDesignTurn",
            ),
            project_event_facts=lambda _event: (),
        )
        turns = (
            SessionWorkTurn(
                text="first",
                plan_id="plan-design",
                step_id="first",
                step_index=0,
            ),
            SessionWorkTurn(
                text="second",
                plan_id="plan-design",
                step_id="second",
                step_index=1,
            ),
        )

        plan_task = asyncio.create_task(
            runtime.submit_plan(
                turns,
                session_id="design-session",
                after_turn=lambda turn, _index, _total: after_turns.append(turn.text),
            )
        )
        await session.first_prompt_started.wait()
        await asyncio.sleep(0)

        assert plan_task.done() is False
        assert session.prompts == ["first"]
        assert after_turns == []

        session.release_first_prompt.set()

        run = await plan_task
        assert run.status == "completed"
        assert session.prompts == ["first", "second"]
        assert after_turns == ["first", "second"]

    asyncio.run(scenario())
