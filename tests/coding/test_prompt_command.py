from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO
from types import SimpleNamespace

from loushang.harness.events import RuntimeEvent


def _runtime_event(payload: dict[str, object]) -> RuntimeEvent[object]:
    return RuntimeEvent(
        event_id="event-1",
        kind=f"agent.{payload['type']}",
        stream_id="session:test",
        sequence=1,
        occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
        payload=payload,
    )


def test_prompt_command_renders_stable_transcript_and_worked() -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.coding.prompt_command import run_prompt_command

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del user_input, images
            assistant = AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="done")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=usage,
                stop_reason="stop",
                error_message=None,
                timestamp=0.0,
            )
            for listener in list(self.listeners):
                listener(
                    {
                        "type": "tool_execution_start",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "args": {"command": "pwd"},
                    }
                )
                listener(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": "t1",
                        "tool_name": "bash",
                        "result": {"content": [], "details": {}},
                        "is_error": False,
                    }
                )
                listener({"type": "message_end", "message": assistant})

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        runtime = FakeRuntime()
        stdout = StringIO()
        exit_code = await run_prompt_command(
            runtime=runtime,
            session=FakeSession(),
            prompt="hello",
            stdout=stdout,
            stderr=StringIO(),
        )

        rendered = stdout.getvalue()
        assert exit_code == 0
        assert "› hello\n" in rendered
        assert "• Ran bash pwd\n" in rendered
        assert "• done\n" in rendered
        assert "─ Worked for " in rendered
        assert "[tool:bash" not in rendered
        assert runtime.dispose_calls == 1

    asyncio.run(scenario())


def test_prompt_plan_command_preserves_transcript_and_uses_one_work_run() -> None:
    from loushang.coding.prompt_command import run_prompt_plan_command
    from loushang.work import InMemoryEventLogBackend
    from loushang.work.session import SessionWorkTurn

    class FakeRuntime:
        def __init__(self) -> None:
            self.dispose_calls = 0

        async def dispose(self) -> None:
            self.dispose_calls += 1

    class FakeSession:
        session_id = "session-1"

        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.listeners = []
            self.runtime_listeners = []

        def get_model_selection(self):
            return None

        def subscribe(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

        def subscribe_runtime_events(self, listener):
            self.runtime_listeners.append(listener)
            return lambda: self.runtime_listeners.remove(listener)

        async def prompt(self, text: str, images=None) -> None:
            del images
            self.prompts.append(text)

    async def scenario() -> None:
        runtime = FakeRuntime()
        session = FakeSession()
        event_log = InMemoryEventLogBackend()
        turns = (
            SessionWorkTurn(
                "inspect", plan_id="plan-1", step_id="step-1", step_index=0
            ),
            SessionWorkTurn("verify", plan_id="plan-1", step_id="step-2", step_index=1),
        )
        stdout = StringIO()

        exit_code = await run_prompt_plan_command(
            runtime=runtime,
            session=session,
            turns=turns,
            stdout=stdout,
            stderr=StringIO(),
            work_event_log=event_log,
        )

        assert exit_code == 0
        assert session.prompts == ["inspect", "verify"]
        assert runtime.dispose_calls == 1
        assert "› inspect\n" in stdout.getvalue()
        assert "› verify\n" in stdout.getvalue()
        entries = event_log.query()
        assert len({entry.run_id for entry in entries}) == 1
        assert [
            entry.payload["kind"]
            for entry in entries
            if entry.payload["kind"].startswith("WorkRun")
        ] == ["WorkRunStarted", "WorkRunCompleted"]

    asyncio.run(scenario())


def test_prompt_command_selects_usable_model_before_prompt() -> None:
    from loushang.ai import Model
    from loushang.ai.model import ModelSelection
    from loushang.coding.prompt_command import run_prompt_command

    kimi = Model(
        id="kimi-for-coding",
        provider="kimi-code",
        endpoint="kimi-code-anthropic",
    )

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.current_model = ModelSelection(
                endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
            )
            self.set_model_calls = []
            self.listeners = []
            self.prompt_calls = []

        def get_model_selection(self):
            return self.current_model

        def get_available_model_details(self):
            return [kimi]

        async def set_model(self, selection):
            self.set_model_calls.append(selection)
            self.current_model = ModelSelection(
                endpoint_id="test-endpoint",
                provider=selection.provider_id,
                model_id=selection.id,
            )

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, self.current_model))

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        session = FakeSession()
        exit_code = await run_prompt_command(
            runtime=FakeRuntime(),
            session=session,
            prompt="hello",
            stdout=StringIO(),
            stderr=StringIO(),
        )

        assert exit_code == 0
        assert session.set_model_calls == [kimi]
        assert session.prompt_calls == [
            (
                "hello",
                ModelSelection(
                    endpoint_id="test-endpoint",
                    provider="kimi-code",
                    model_id="kimi-for-coding",
                ),
            )
        ]

    asyncio.run(scenario())


def test_prompt_command_work_event_log_records_prompt_turn() -> None:
    from loushang.coding.prompt_command import run_prompt_command
    from loushang.work import InMemoryEventLogBackend

    class FakeRuntime:
        pass

    class FakeSession:
        session_id = "session-1"

        def __init__(self) -> None:
            self.listeners = []
            self.runtime_listeners = []

        def get_model_selection(self):
            return None

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        def subscribe_runtime_events(self, listener):
            self.runtime_listeners.append(listener)

            def unsubscribe() -> None:
                self.runtime_listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del user_input, images
            payload = {
                "type": "message_update",
                "message": {"role": "assistant"},
                "assistant_message_event": {"type": "text_delta", "text": "done"},
            }
            for listener in list(self.listeners):
                result = listener(payload)
                if result is not None:
                    await result
            for listener in list(self.runtime_listeners):
                result = listener(_runtime_event(payload))
                if result is not None:
                    await result

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        exit_code = await run_prompt_command(
            runtime=FakeRuntime(),
            session=FakeSession(),
            prompt="hello",
            stdout=StringIO(),
            stderr=StringIO(),
            work_event_log=event_log,
            method_id="method:task:review",
        )

        assert exit_code == 0
        entries = event_log.query(session_id="session-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ContentDelta",
            "WorkRunCompleted",
        ]
        assert entries[0].payload["payload"]["method_id"] == "method:task:review"
        assert entries[1].payload["payload"]["method_id"] == "method:task:review"
        assert entries[3].payload["payload"]["method_id"] == "method:task:review"

    asyncio.run(scenario())


def test_prompt_command_does_not_render_worked_after_assistant_error() -> None:
    from loushang.coding.prompt_command import run_prompt_command

    class FakeRuntime:
        pass

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []
            self.messages = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            del user_input, images
            assistant = SimpleNamespace(
                role="assistant",
                content=[],
                stop_reason="error",
                error_message="Endpoint not found for model: unknown:unknown:unknown",
            )
            self.messages.append(assistant)
            for listener in list(self.listeners):
                listener({"type": "message_end", "message": assistant})

        async def wait_for_idle(self) -> None:
            return None

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_prompt_command(
            runtime=FakeRuntime(),
            session=FakeSession(),
            prompt="hello",
            stdout=stdout,
            stderr=stderr,
        )

        rendered = stdout.getvalue()
        assert exit_code == 1
        assert (
            "■ Error: Endpoint not found for model: unknown:unknown:unknown" in rendered
        )
        assert "Worked for" not in rendered
        assert stderr.getvalue() == ""

    asyncio.run(scenario())


def test_prompt_command_runs_follow_ups_with_images_only_on_first_turn() -> None:
    from loushang.coding.prompt_command import run_prompt_command

    image = object()

    class FakeRuntime:
        async def dispose(self) -> None:
            raise AssertionError("dispose must not run")

    class FakeSession:
        def __init__(self) -> None:
            self.listeners = []
            self.prompt_calls = []

        def subscribe(self, listener):
            self.listeners.append(listener)

            def unsubscribe() -> None:
                self.listeners.remove(listener)

            return unsubscribe

        async def prompt(self, user_input: str, images=None) -> None:
            self.prompt_calls.append((user_input, images))

    async def scenario() -> None:
        session = FakeSession()
        stdout = StringIO()
        exit_code = await run_prompt_command(
            runtime=FakeRuntime(),
            session=session,
            prompt="first",
            images=[image],
            follow_up_messages=("second", "third"),
            stdout=stdout,
            stderr=StringIO(),
            dispose=False,
        )

        assert exit_code == 0
        assert session.prompt_calls == [
            ("first", [image]),
            ("second", None),
            ("third", None),
        ]
        assert session.listeners == []
        assert stdout.getvalue().count("─ Worked for ") == 3

    asyncio.run(scenario())
