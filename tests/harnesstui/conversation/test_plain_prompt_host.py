from __future__ import annotations

import asyncio
import subprocess
import sys
from io import StringIO

import pytest

from loushang.harnesstui.conversation.plain_prompt_host import (
    PlainPromptHostPorts,
    PlainPromptPlanHostPorts,
    PreparedPlainPromptPlanRun,
    PreparedPlainPromptRun,
    dispose_runtime_or_session,
    last_assistant_failure_message,
    run_plain_prompt_host,
    run_plain_prompt_plan_host,
    session_identity,
    session_messages,
)


def test_plain_prompt_host_stays_product_neutral_on_fresh_import() -> None:
    script = """
import sys

import loushang.harnesstui.conversation.plain_prompt_host

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_plain_prompt_host_owns_turn_order_and_cleanup() -> None:
    events: list[str] = []
    ticks = iter((10.0, 12.0, 20.0, 25.0))

    async def prepare() -> None:
        events.append("prepare")

    def subscribe():
        events.append("subscribe")

        def unsubscribe() -> None:
            events.append("unsubscribe")

        return unsubscribe

    async def submit(prompt: str, turn_index: int, turn_count: int) -> None:
        events.append(f"submit:{turn_index}/{turn_count}:{prompt}")

    def capture_failure_state() -> int:
        events.append("capture")
        return 0

    def resolve_failure(previous: int) -> str | None:
        events.append(f"resolve:{previous}")
        return None

    async def dispose() -> None:
        events.append("dispose")

    result = asyncio.run(
        run_plain_prompt_host(
            PreparedPlainPromptRun(
                prompts=("first", "second"),
                ports=PlainPromptHostPorts(
                    prepare=prepare,
                    subscribe=subscribe,
                    submit=submit,
                    capture_failure_state=capture_failure_state,
                    resolve_failure=resolve_failure,
                    render_user=lambda prompt: events.append(f"user:{prompt}"),
                    render_worked=lambda elapsed: events.append(
                        f"worked:{elapsed:.1f}"
                    ),
                    render_error=lambda message: events.append(f"error:{message}"),
                    dispose=dispose,
                ),
                stderr=StringIO(),
                now=lambda: next(ticks),
            )
        )
    )

    assert result == 0
    assert events == [
        "prepare",
        "subscribe",
        "capture",
        "user:first",
        "submit:0/2:first",
        "resolve:0",
        "worked:2.0",
        "capture",
        "user:second",
        "submit:1/2:second",
        "resolve:0",
        "worked:5.0",
        "unsubscribe",
        "dispose",
    ]


def test_plain_prompt_plan_host_owns_work_hooks_and_cleanup() -> None:
    events: list[str] = []
    ticks = iter((10.0, 12.0, 20.0, 25.0))

    async def prepare() -> None:
        events.append("prepare")

    async def submit_plan(turns, before_turn, after_turn) -> None:
        for index, turn in enumerate(turns):
            await before_turn(turn, index, len(turns))
            events.append(f"submit:{turn}")
            await after_turn(turn, index, len(turns))

    async def dispose() -> None:
        events.append("dispose")

    result = asyncio.run(
        run_plain_prompt_plan_host(
            PreparedPlainPromptPlanRun(
                turns=("research", "verify"),
                ports=PlainPromptPlanHostPorts(
                    prepare=prepare,
                    subscribe=lambda: (
                        events.append("subscribe")
                        or (lambda: events.append("unsubscribe"))
                    ),
                    submit_plan=submit_plan,
                    turn_text=str,
                    capture_failure_state=lambda: 0,
                    resolve_failure=lambda _previous: None,
                    render_user=lambda text: events.append(f"user:{text}"),
                    render_worked=lambda elapsed: events.append(
                        f"worked:{elapsed:.1f}"
                    ),
                    render_error=lambda text: events.append(f"error:{text}"),
                    dispose=dispose,
                ),
                stderr=StringIO(),
                now=lambda: next(ticks),
            )
        )
    )

    assert result == 0
    assert events == [
        "prepare",
        "subscribe",
        "user:research",
        "submit:research",
        "worked:2.0",
        "user:verify",
        "submit:verify",
        "worked:5.0",
        "unsubscribe",
        "dispose",
    ]


def test_plain_prompt_host_stops_after_product_reports_failure() -> None:
    events: list[str] = []
    failure_version = 0

    async def prepare() -> None:
        return None

    def subscribe():
        return lambda: events.append("unsubscribe")

    async def submit(prompt: str, turn_index: int, _turn_count: int) -> None:
        nonlocal failure_version
        events.append(f"submit:{prompt}")
        if turn_index == 1:
            failure_version += 1

    async def dispose() -> None:
        events.append("dispose")

    result = asyncio.run(
        run_plain_prompt_host(
            PreparedPlainPromptRun(
                prompts=("first", "failed", "not-run"),
                ports=PlainPromptHostPorts(
                    prepare=prepare,
                    subscribe=subscribe,
                    submit=submit,
                    capture_failure_state=lambda: failure_version,
                    resolve_failure=lambda previous: (
                        "product failure" if previous != failure_version else None
                    ),
                    render_user=lambda prompt: events.append(f"user:{prompt}"),
                    render_worked=lambda _elapsed: events.append("worked"),
                    render_error=lambda message: events.append(f"error:{message}"),
                    dispose=dispose,
                ),
                stderr=StringIO(),
                now=lambda: 0.0,
            )
        )
    )

    assert result == 1
    assert events == [
        "user:first",
        "submit:first",
        "worked",
        "user:failed",
        "submit:failed",
        "unsubscribe",
        "dispose",
    ]


def test_plain_prompt_host_presents_run_exception_and_verbose_traceback() -> None:
    events: list[str] = []
    stderr = StringIO()

    async def prepare() -> None:
        return None

    def subscribe():
        return lambda: events.append("unsubscribe")

    async def submit(_prompt: str, _turn_index: int, _turn_count: int) -> None:
        raise RuntimeError("prompt failed")

    async def dispose() -> None:
        events.append("dispose")

    result = asyncio.run(
        run_plain_prompt_host(
            PreparedPlainPromptRun(
                prompts=("first",),
                ports=PlainPromptHostPorts(
                    prepare=prepare,
                    subscribe=subscribe,
                    submit=submit,
                    capture_failure_state=lambda: None,
                    resolve_failure=lambda _previous: None,
                    render_user=lambda prompt: events.append(f"user:{prompt}"),
                    render_worked=lambda _elapsed: events.append("worked"),
                    render_error=lambda message: events.append(f"error:{message}"),
                    dispose=dispose,
                ),
                stderr=stderr,
                verbose=True,
                now=lambda: 0.0,
            )
        )
    )

    assert result == 1
    assert events == [
        "user:first",
        "error:prompt failed",
        "unsubscribe",
        "dispose",
    ]
    assert "RuntimeError: prompt failed" in stderr.getvalue()


def test_plain_prompt_host_presents_dispose_failure() -> None:
    errors: list[str] = []

    async def prepare() -> None:
        return None

    async def submit(_prompt: str, _turn_index: int, _turn_count: int) -> None:
        return None

    async def dispose() -> None:
        raise RuntimeError("dispose failed")

    result = asyncio.run(
        run_plain_prompt_host(
            PreparedPlainPromptRun(
                prompts=("first",),
                ports=PlainPromptHostPorts(
                    prepare=prepare,
                    subscribe=lambda: lambda: None,
                    submit=submit,
                    capture_failure_state=lambda: None,
                    resolve_failure=lambda _previous: None,
                    render_user=lambda _prompt: None,
                    render_worked=lambda _elapsed: None,
                    render_error=errors.append,
                    dispose=dispose,
                ),
                stderr=StringIO(),
                now=lambda: 0.0,
            )
        )
    )

    assert result == 1
    assert errors == ["dispose failed"]


def test_plain_prompt_host_preserves_unsubscribe_failure_boundary() -> None:
    dispose_calls = 0

    async def prepare() -> None:
        return None

    def subscribe():
        def unsubscribe() -> None:
            raise RuntimeError("unsubscribe failed")

        return unsubscribe

    async def submit(_prompt: str, _turn_index: int, _turn_count: int) -> None:
        return None

    async def dispose() -> None:
        nonlocal dispose_calls
        dispose_calls += 1

    run = PreparedPlainPromptRun(
        prompts=("first",),
        ports=PlainPromptHostPorts(
            prepare=prepare,
            subscribe=subscribe,
            submit=submit,
            capture_failure_state=lambda: None,
            resolve_failure=lambda _previous: None,
            render_user=lambda _prompt: None,
            render_worked=lambda _elapsed: None,
            render_error=lambda _message: None,
            dispose=dispose,
        ),
        stderr=StringIO(),
        now=lambda: 0.0,
    )

    with pytest.raises(RuntimeError, match="unsubscribe failed"):
        asyncio.run(run_plain_prompt_host(run))

    assert dispose_calls == 0


def test_plain_prompt_session_helpers_support_standard_product_shapes() -> None:
    class Session:
        session_id = "research-session"

        def get_session_context(self):
            return type(
                "Context",
                (),
                {
                    "messages": (
                        type("User", (), {"role": "user"})(),
                        type(
                            "Assistant",
                            (),
                            {
                                "role": "assistant",
                                "stop_reason": "error",
                                "error_message": "provider unavailable",
                            },
                        )(),
                    )
                },
            )()

    session = Session()

    assert len(session_messages(session)) == 2
    assert last_assistant_failure_message(session) == "provider unavailable"
    assert session_identity(session) == "research-session"


def test_plain_prompt_disposal_prefers_runtime_then_session() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        class Runtime:
            async def dispose(self) -> None:
                calls.append("runtime")

        class Session:
            async def dispose(self) -> None:
                calls.append("session")

        session = Session()
        await dispose_runtime_or_session(Runtime(), session)
        await dispose_runtime_or_session(object(), session)

        assert calls == ["runtime", "session"]

    asyncio.run(scenario())
