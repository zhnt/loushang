from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.harness.session import SessionFacade, SessionFacadePorts
from loushang.harness.session.facade import SessionModelPort as FacadeModelPort
from loushang.harness.session.facade_optional import (
    SessionFacadeOptionalOperations,
    SessionModelPort,
)
from loushang.harness.workspace.exec import ExecOutputChunk


class _Queue:
    def __init__(self) -> None:
        self.steering = ["steer"]
        self.follow_up = ["follow"]

    @property
    def pending_message_count(self) -> int:
        return len(self.steering) + len(self.follow_up)

    def get_steering_messages(self) -> list[str]:
        return list(self.steering)

    def get_follow_up_messages(self) -> list[str]:
        return list(self.follow_up)

    def clear_queue(self) -> dict[str, list[str]]:
        cleared = {
            "steering": self.get_steering_messages(),
            "follow_up": self.get_follow_up_messages(),
        }
        self.steering.clear()
        self.follow_up.clear()
        return cleared


class _Runtime:
    def __init__(self) -> None:
        self.queue = _Queue()
        self.prompt_calls: list[tuple[str, str | None]] = []
        self.steer_calls: list[str] = []
        self.follow_up_calls: list[str] = []
        self.continued = False
        self.aborted = False
        self.waited = False
        self.listener = None

    def subscribe(self, listener):
        self.listener = listener

        def unsubscribe() -> None:
            self.listener = None

        return unsubscribe

    async def prompt(self, user_input, *, source=None, **kwargs) -> None:
        del kwargs
        self.prompt_calls.append((user_input, source))

    def steer(self, user_input, **kwargs) -> None:
        del kwargs
        self.steer_calls.append(user_input)

    def follow_up(self, user_input, **kwargs) -> None:
        del kwargs
        self.follow_up_calls.append(user_input)

    async def continue_run(self) -> None:
        self.continued = True

    def abort(self) -> bool:
        self.aborted = True
        return True

    async def wait_for_idle(self) -> None:
        self.waited = True


@dataclass(frozen=True)
class _Context:
    value: str


@dataclass(frozen=True)
class _Record:
    session_id: str


class _Transcript:
    def build_session_context(self) -> _Context:
        return _Context("context")

    def get_session_record(self) -> _Record:
        return _Record("session-1")

    def get_session_file(self) -> object | None:
        return "/tmp/session.jsonl"


@dataclass(frozen=True)
class _Tool:
    name: str


class _Tools:
    def get_active_tool_names(self) -> list[str]:
        return ["read"]

    def get_all_tools(self) -> list[_Tool]:
        return [_Tool("read")]

    def get_tool_definition(self, name: str) -> _Tool | None:
        return _Tool(name) if name == "read" else None


class _Commands:
    def list_commands(self) -> list[str]:
        return ["review"]

    async def execute_command_async(self, invocation_name: str, args: str) -> str:
        return f"{invocation_name}:{args}"


class _CommandExecution:
    is_running = False
    has_pending_messages = False

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.aborted = False

    async def execute(self, command: str, **kwargs) -> dict[str, object]:
        on_output = kwargs.get("on_output")
        if on_output is not None:
            result = on_output(ExecOutputChunk(stream="stdout", text="partial"))
            if asyncio.iscoroutine(result):
                await result
        self.commands.append(command)
        return {"output": "complete", "exit_code": 0}

    def abort(self) -> None:
        self.aborted = True


class _View:
    def get_state(
        self, *, steering: list[str], follow_up: list[str]
    ) -> dict[str, object]:
        return {"steering": steering, "follow_up": follow_up}

    def get_context_usage(self) -> dict[str, int]:
        return {"tokens": 12}

    def get_user_messages_for_forking(self) -> list[dict[str, str]]:
        return [{"entry_id": "user-1", "text": "hello"}]

    def get_entry_text(self, entry_id: str) -> str | None:
        return "hello" if entry_id == "user-1" else None

    def get_last_assistant_text(self) -> str | None:
        return "done"

    def get_recent_assistant_texts(self) -> tuple[str, ...]:
        return ("done", "previous")


class _Retry:
    is_retrying = True

    def __init__(self) -> None:
        self.aborted = False
        self.waited = False

    def abort(self) -> None:
        self.aborted = True

    async def wait(self) -> None:
        self.waited = True


class _Identity:
    def __init__(self) -> None:
        self.session_id = "session-1"
        self.session_name: str | None = "Initial name"
        self.updated_names: list[str | None] = []

    async def set_session_name(self, name: str | None) -> None:
        self.updated_names.append(name)
        self.session_name = name


class _Maintenance:
    def __init__(self) -> None:
        self.is_compacting = False
        self.auto_retry_enabled = True
        self.auto_compaction_enabled = True
        self.retry_updates: list[bool] = []
        self.compaction_updates: list[bool] = []
        self.compact_calls: list[str | None] = []
        self.aborted = False

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.retry_updates.append(enabled)
        self.auto_retry_enabled = enabled

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.compaction_updates.append(enabled)
        self.auto_compaction_enabled = enabled

    async def compact(self, custom_instructions: str | None = None) -> object:
        self.compact_calls.append(custom_instructions)
        return {"summary": "compacted"}

    def abort_compaction(self) -> None:
        self.aborted = True


class _Resources:
    def __init__(self) -> None:
        self.refreshes = 0
        self.requests = 0

    def get_prompt_templates(self) -> list[object]:
        return ["review", "release"]

    async def refresh_resources(self) -> None:
        self.refreshes += 1

    def request_resource_refresh(self) -> None:
        self.requests += 1


class _Diagnostics:
    def get_last_diagnostics(self, limit: int = 50) -> list[str]:
        return [f"last:{limit}"]

    def get_diagnostics(self, query=None) -> list[str]:
        return [f"all:{query}"]

    def get_session_diagnostics(self, query=None) -> list[str]:
        return [f"session:{query}"]

    def get_diagnostics_summary(self, query=None) -> str:
        return f"summary:{query}"

    def get_session_diagnostics_summary(self, query=None) -> str:
        return f"session-summary:{query}"

    def get_last_error_report(self) -> str:
        return "error-report"


class _Packages:
    def get_packages(self, *, catalog_path: str | None = None) -> list[dict[str, object]]:
        return [{"catalog_path": catalog_path}]

    async def materialize_package(self, source: str) -> dict[str, object]:
        return {"operation": "materialize", "source": source}

    async def install_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return {"operation": "install", "source": source, "scope": scope}

    async def update_package(self, source: str) -> dict[str, object]:
        return {"operation": "update", "source": source}

    async def update_packages(self) -> list[dict[str, object]]:
        return [{"operation": "update_all"}]

    async def check_package_updates(self) -> list[dict[str, object]]:
        return [{"operation": "check_updates"}]

    def remove_package(self, source: str) -> dict[str, object]:
        return {"operation": "remove", "source": source}

    def uninstall_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return {"operation": "uninstall", "source": source, "scope": scope}


def _facade():
    runtime = _Runtime()
    command_execution = _CommandExecution()
    retry = _Retry()
    identity = _Identity()
    maintenance = _Maintenance()
    resources = _Resources()
    return (
        SessionFacade.from_ports(
            runtime=runtime,
            ports=SessionFacadePorts(
                transcript=_Transcript(),
                tools=_Tools(),
                commands=_Commands(),
                command_execution=command_execution,
                view=_View(),
                retry=retry,
                identity=identity,
                maintenance=maintenance,
                resources=resources,
            ),
        ),
        runtime,
        command_execution,
        retry,
        identity,
        maintenance,
        resources,
    )


def test_session_facade_composes_standard_read_and_queue_operations() -> None:
    facade, runtime, _, _, identity, maintenance, resources = _facade()

    assert facade.get_state() == {"steering": ["steer"], "follow_up": ["follow"]}
    assert facade.get_session_context() == _Context("context")
    assert facade.get_session_record() == _Record("session-1")
    assert facade.get_session_file() == "/tmp/session.jsonl"
    assert facade.get_active_tool_names() == ["read"]
    assert facade.get_all_tools() == [_Tool("read")]
    assert facade.get_tool_definition("missing") is None
    assert facade.list_commands() == ["review"]
    assert facade.get_context_usage() == {"tokens": 12}
    assert facade.get_user_messages_for_forking() == [
        {"entry_id": "user-1", "text": "hello"}
    ]
    assert facade.get_entry_text("user-1") == "hello"
    assert facade.get_last_assistant_text() == "done"
    assert facade.get_recent_assistant_texts() == ("done", "previous")
    assert facade.session_id == "session-1"
    assert facade.session_name == "Initial name"
    assert facade.is_compacting is False
    assert facade.auto_retry_enabled is True
    assert facade.auto_compaction_enabled is True
    assert facade.get_prompt_templates() == ["review", "release"]

    facade.steer("second steer")
    facade.follow_up("second follow")

    assert runtime.steer_calls == ["second steer"]
    assert runtime.follow_up_calls == ["second follow"]
    assert facade.pending_message_count == 2
    assert facade.clear_queue() == {
        "steering": ["steer"],
        "follow_up": ["follow"],
    }

    async def update_controls() -> None:
        await facade.set_session_name("Renamed")
        assert await facade.compact("Keep the current task") == {"summary": "compacted"}
        await facade.refresh_resources()

    asyncio.run(update_controls())
    facade.set_auto_retry_enabled(False)
    facade.set_auto_compaction_enabled(False)
    facade.abort_compaction()

    assert identity.updated_names == ["Renamed"]
    assert facade.session_name == "Renamed"
    assert maintenance.retry_updates == [False]
    assert maintenance.compaction_updates == [False]
    assert maintenance.compact_calls == ["Keep the current task"]
    assert maintenance.aborted is True
    assert resources.refreshes == 1
    facade.request_resource_refresh()
    assert resources.requests == 1


def test_session_facade_forwards_execution_events_and_controls() -> None:
    facade, runtime, command_execution, retry, _, _, _ = _facade()
    chunks: list[ExecOutputChunk] = []
    received: list[str] = []

    async def scenario() -> None:
        await facade.prompt("hello", source="extension")
        assert await facade.execute_command_async("review", "diff") == "review:diff"
        assert await facade.execute_command_tool(
            "echo ok", on_output=chunks.append
        ) == {
            "output": "complete",
            "exit_code": 0,
        }
        await facade.continue_run()
        await facade.wait_for_idle()
        await facade.wait_for_retry()

    unsubscribe = facade.subscribe(received.append, project=lambda event: event)
    asyncio.run(scenario())
    assert runtime.listener is not None
    runtime.listener("event-1")
    unsubscribe()

    assert runtime.prompt_calls == [("hello", "extension")]
    assert command_execution.commands == ["echo ok"]
    assert chunks == [ExecOutputChunk(stream="stdout", text="partial")]
    assert runtime.continued is True
    assert runtime.waited is True
    assert retry.waited is True
    assert received == ["event-1"]

    assert facade.abort() is True
    facade.abort_command()
    facade.abort_retry()

    assert runtime.aborted is True
    assert command_execution.aborted is True
    assert retry.aborted is True
    assert facade.is_retrying is True


def test_session_facade_forwards_optional_diagnostics_and_package_ports() -> None:
    runtime = _Runtime()
    diagnostics = _Diagnostics()
    packages = _Packages()
    facade = SessionFacade.from_ports(
        runtime=runtime,
        ports=SessionFacadePorts(
            transcript=_Transcript(),
            tools=_Tools(),
            commands=_Commands(),
            command_execution=_CommandExecution(),
            view=_View(),
            retry=_Retry(),
            identity=_Identity(),
            maintenance=_Maintenance(),
            resources=_Resources(),
            diagnostics=diagnostics,
            packages=packages,
        ),
    )

    assert facade.get_last_diagnostics(3) == ["last:3"]
    assert facade.get_diagnostics("query") == ["all:query"]
    assert facade.get_session_diagnostics("query") == ["session:query"]
    assert facade.get_diagnostics_summary("query") == "summary:query"
    assert facade.get_session_diagnostics_summary("query") == "session-summary:query"
    assert facade.get_last_error_report() == "error-report"
    assert facade.get_packages(catalog_path="catalog.json") == [
        {"catalog_path": "catalog.json"}
    ]

    async def package_operations() -> None:
        assert await facade.materialize_package("git:one") == {
            "operation": "materialize",
            "source": "git:one",
        }
        assert await facade.install_package("git:one", scope="global") == {
            "operation": "install",
            "source": "git:one",
            "scope": "global",
        }
        assert await facade.update_package("git:one") == {
            "operation": "update",
            "source": "git:one",
        }
        assert await facade.update_packages() == [{"operation": "update_all"}]
        assert await facade.check_package_updates() == [{"operation": "check_updates"}]

    asyncio.run(package_operations())
    assert facade.remove_package("git:one") == {
        "operation": "remove",
        "source": "git:one",
    }
    assert facade.uninstall_package("git:one", scope="global") == {
        "operation": "uninstall",
        "source": "git:one",
        "scope": "global",
    }


def test_session_facade_keeps_optional_capability_compatibility_exports() -> None:
    assert FacadeModelPort is SessionModelPort
    assert issubclass(SessionFacade, SessionFacadeOptionalOperations)
    assert SessionFacade.get_model_selection is (
        SessionFacadeOptionalOperations.get_model_selection
    )
