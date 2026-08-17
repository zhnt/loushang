from __future__ import annotations

import asyncio
import inspect

import pytest

from loushang.harness.extensions.agent.replacement import ExtensionReplacementRuntime
from loushang.harness.runtime import SessionOperationResult


class Session:
    def __init__(self, name: str) -> None:
        self.name = name
        self.session_manager = f"manager:{name}"

    def create_replaced_session_context(self) -> str:
        return f"context:{self.name}"


class RuntimeHost:
    def __init__(self, before: Session, after: Session) -> None:
        self.current: Session = before
        self.after = after
        self.calls: list[tuple[str, object]] = []

    async def fork_session_operation(
        self,
        entry_id: str,
        *,
        position: str = "at",
        with_session=None,
    ) -> SessionOperationResult[Session, str | None]:
        self.calls.append(("fork_operation", (entry_id, position)))
        previous = self.current
        self.current = self.after
        await _run_callback(with_session, self.after.create_replaced_session_context())
        return SessionOperationResult(
            previous=previous,
            current=self.after,
            payload="selected text",
            cancelled=False,
        )

    async def new_session_operation(
        self,
        *,
        parent_session: str | None = None,
        setup=None,
        with_session=None,
    ) -> SessionOperationResult[Session, None]:
        self.calls.append(("new_operation", parent_session))
        previous = self.current
        self.current = self.after
        await _run_callback(setup, self.after.session_manager)
        await _run_callback(with_session, self.after.create_replaced_session_context())
        return SessionOperationResult(
            previous=previous,
            current=self.after,
            payload=None,
            cancelled=False,
        )

    async def restore_session_operation(
        self,
        session_path: str,
        *,
        with_session=None,
    ) -> SessionOperationResult[Session, None]:
        self.calls.append(("restore_operation", session_path))
        previous = self.current
        self.current = self.after
        await _run_callback(with_session, self.after.create_replaced_session_context())
        return SessionOperationResult(
            previous=previous,
            current=self.after,
            payload=None,
            cancelled=False,
        )


async def _run_callback(callback, argument) -> None:
    if callback is None:
        return
    if not inspect.iscoroutinefunction(callback):
        raise TypeError("withSession callback must be an async callable.")
    await callback(argument)


class CommandContext:
    def __init__(self, cwd: str) -> None:
        self._cwd = cwd
        self.invalidated = False

    @property
    def cwd(self) -> str:
        if self.invalidated:
            raise RuntimeError("stale context")
        return self._cwd


class Runner:
    def __init__(self) -> None:
        self.contexts: list[CommandContext] = []

    def create_command_context(self, *, fallback_cwd: str) -> CommandContext:
        context = CommandContext(fallback_cwd)
        self.contexts.append(context)
        return context


class ReplacedSession:
    def __init__(self, runner: Runner | None = None) -> None:
        self.extension_runner = runner
        self.session_manager = type(
            "SessionManager", (), {"get_cwd": lambda self: "/tmp/project"}
        )()
        self.messages: list[tuple[object, object | None]] = []
        self.user_messages: list[tuple[object, object | None]] = []

    async def _send_message_from_extension(
        self, message: object, options: object | None = None
    ) -> None:
        self.messages.append((message, options))

    async def _send_user_message_from_extension_async(
        self, content: object, options: object | None = None
    ) -> None:
        self.user_messages.append((content, options))


def test_extension_replacement_controller_forks_and_runs_with_session_callback() -> (
    None
):
    before = Session("before")
    after = Session("after")
    host = RuntimeHost(before, after)
    events: list[tuple[str, object]] = []

    async def _with_session(context):
        events.append(("withSession", context))

    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: host)

    result = asyncio.run(
        controller.fork("entry-1", {"position": "before", "withSession": _with_session})
    )

    assert result == {
        "cancelled": False,
        "selected_text": "selected text",
    }
    assert host.calls == [("fork_operation", ("entry-1", "before"))]
    assert events == [("withSession", "context:after")]


def test_extension_replacement_controller_new_session_runs_setup_before_with_session() -> (
    None
):
    before = Session("before")
    after = Session("after")
    host = RuntimeHost(before, after)
    events: list[tuple[str, object]] = []

    async def _setup(session_manager):
        events.append(("setup", session_manager))

    async def _with_session(context):
        events.append(("withSession", context))

    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: host)

    result = asyncio.run(
        controller.new_session(
            {
                "parentSession": "parent.jsonl",
                "setup": _setup,
                "withSession": _with_session,
            }
        )
    )

    assert result == {"cancelled": False}
    assert host.calls == [("new_operation", "parent.jsonl")]
    assert events == [("setup", "manager:after"), ("withSession", "context:after")]


def test_extension_replacement_controller_reports_cancelled_without_runtime_host() -> (
    None
):
    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: None)

    assert asyncio.run(controller.fork("entry-1")) == {"cancelled": True}
    assert asyncio.run(controller.new_session()) == {"cancelled": True}
    assert asyncio.run(controller.switch_session("/tmp/session.jsonl")) == {
        "cancelled": True
    }


def test_extension_replacement_controller_validates_callbacks_and_fork_position() -> (
    None
):
    host = RuntimeHost(Session("before"), Session("after"))
    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: host)

    with pytest.raises(ValueError, match="Unsupported fork position"):
        asyncio.run(controller.fork("entry-1", {"position": "after"}))

    with pytest.raises(
        TypeError, match="withSession callback must be an async callable"
    ):
        asyncio.run(
            controller.switch_session(
                "/tmp/session.jsonl", {"withSession": lambda context: None}
            )
        )


def test_extension_replacement_controller_creates_replaced_command_context() -> None:
    runner = Runner()
    session = ReplacedSession(runner)
    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: None)

    async def scenario() -> None:
        context = controller.create_context(session)
        assert context.cwd == "/tmp/project"

        await context.send_message({"customType": "demo"}, {"display": True})
        await context.send_message({"customType": "snake"}, None)
        await context.send_user_message("run this", {"deliverAs": "followUp"})
        await context.send_user_message("and this", None)

    asyncio.run(scenario())

    assert session.messages == [
        ({"customType": "demo"}, {"display": True}),
        ({"customType": "snake"}, None),
    ]
    assert session.user_messages == [
        ("run this", {"deliverAs": "followUp"}),
        ("and this", None),
    ]


def test_extension_replacement_controller_replaced_context_send_methods_obey_stale_guard() -> (
    None
):
    runner = Runner()
    session = ReplacedSession(runner)
    controller = ExtensionReplacementRuntime(get_runtime_host=lambda: None)
    context = controller.create_context(session)
    context.invalidated = True

    with pytest.raises(RuntimeError, match="stale context"):
        asyncio.run(context.send_message({"customType": "demo"}, None))
    with pytest.raises(RuntimeError, match="stale context"):
        asyncio.run(context.send_user_message("run this", None))
