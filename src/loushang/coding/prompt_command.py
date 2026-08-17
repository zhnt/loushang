from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from loushang.coding.adapters.harnesswork import create_coding_work_runtime
from loushang.coding.model_selection import ensure_usable_session_model
from loushang.coding.presentation.tui.plain import PlainCodingUiRenderer
from loushang.harnesstui.conversation.agent_binding import (
    run_agent_plain_prompt,
    run_agent_plain_prompt_plan,
)
from loushang.harnesstui.conversation.plain_prompt_host import session_identity
from loushang.harnesswork import EventLogBackend
from loushang.harnesswork.integrations.session import (
    SessionWorkRuntime,
    SessionWorkTurn,
    require_session_work_turn,
    submit_session_turn,
)


async def run_prompt_command(
    *,
    runtime: Any,
    session: Any,
    prompt: str,
    stdout: TextIO,
    stderr: TextIO,
    images: list[object] | None = None,
    follow_up_messages: Sequence[str] = (),
    verbose: bool = False,
    work_event_log: EventLogBackend | None = None,
    work_runtime: SessionWorkRuntime | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    planned_constraint: Mapping[str, object] | None = None,
    audit_policy: Mapping[str, object] | None = None,
    plan_facts: Mapping[str, object] | None = None,
    step_facts: Mapping[str, object] | None = None,
    dispose: bool = True,
) -> int:
    """Run one product prompt and render the stable coding transcript."""

    renderer = PlainCodingUiRenderer(stdout=stdout, stderr=stderr)
    turn_work_runtime: SessionWorkRuntime | Callable[[], SessionWorkRuntime] | None = (
        None
    )
    if work_event_log is not None:
        turn_work_runtime = work_runtime or (
            lambda: create_coding_work_runtime(
                session=session,
                event_log=work_event_log,
                session_id=lambda: session_identity(session),
            )
        )

    async def submit_turn(text: str, turn_index: int, turn_count: int) -> None:
        del turn_count
        await submit_session_turn(
            session,
            SessionWorkTurn(
                text=text,
                images=images if turn_index == 0 else None,
                method_id=method_id if turn_index == 0 else None,
                plan_id=plan_id if turn_index == 0 else None,
                step_id=step_id if turn_index == 0 else None,
                step_index=step_index if turn_index == 0 else None,
                step_title=step_title if turn_index == 0 else None,
                planned_constraint=planned_constraint if turn_index == 0 else None,
                audit_policy=audit_policy if turn_index == 0 else None,
                plan_facts=plan_facts if turn_index == 0 else None,
                step_facts=step_facts if turn_index == 0 else None,
            ),
            session_id=(
                session_identity(session) if turn_work_runtime is not None else ""
            ),
            work_runtime=turn_work_runtime,
        )

    return await run_agent_plain_prompt(
        runtime=runtime,
        session=session,
        prompts=(prompt, *follow_up_messages),
        renderer=renderer,
        prepare=lambda: ensure_usable_session_model(session),
        submit=submit_turn,
        stderr=stderr,
        verbose=verbose,
        dispose=dispose,
    )


async def run_prompt_plan_command(
    *,
    runtime: Any,
    session: Any,
    turns: Sequence[SessionWorkTurn],
    stdout: TextIO,
    stderr: TextIO,
    work_event_log: EventLogBackend,
    work_runtime: SessionWorkRuntime | None = None,
    verbose: bool = False,
    dispose: bool = True,
) -> int:
    """Render and execute a fixed MethodPlan as one Work-owned run."""

    renderer = PlainCodingUiRenderer(stdout=stdout, stderr=stderr)

    async def submit_plan(
        prepared_turns: Sequence[object],
        before_turn: Any,
        after_turn: Any,
    ) -> None:
        resolved_work_runtime = work_runtime or create_coding_work_runtime(
            session=session,
            event_log=work_event_log,
            session_id=lambda: session_identity(session),
        )
        await resolved_work_runtime.submit_plan(
            tuple(require_session_work_turn(turn) for turn in prepared_turns),
            session_id=session_identity(session),
            before_turn=before_turn,
            after_turn=after_turn,
        )

    return await run_agent_plain_prompt_plan(
        runtime=runtime,
        session=session,
        turns=turns,
        renderer=renderer,
        prepare=lambda: ensure_usable_session_model(session),
        submit_plan=submit_plan,
        turn_text=lambda turn: require_session_work_turn(turn).text,
        stderr=stderr,
        verbose=verbose,
        dispose=dispose,
    )


__all__ = ["run_prompt_command", "run_prompt_plan_command"]
