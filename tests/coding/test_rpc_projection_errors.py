from __future__ import annotations

import asyncio
import json
from io import StringIO
from types import SimpleNamespace

from loushang.ai.model import ModelSelection
from loushang.ai.model.domain import (
    Capabilities,
    Endpoint,
    Model,
    OpenAICompletionsConfig,
    Pricing,
)
from tests.coding.rpc_support import (
    FakeModelRegistry,
    FakeRuntime,
    FakeSession,
    _assistant_message,
    _parse_jsonl,
    _user_message,
)


def test_rpc_mode_get_messages_skips_invalid_entries_when_serialization_fails() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenMessageSession(FakeSession):
        def get_session_context(self):
            return SimpleNamespace(
                messages=[
                    _assistant_message("ok"),
                    object(),
                    _user_message("follow"),
                ]
            )

    session = BrokenMessageSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "messages", "type": "get_messages"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    lines = _parse_jsonl(stdout)
    assert lines[0]["type"] == "response"
    assert lines[0]["command"] == "get_messages"
    assert lines[0]["success"] is True
    assert len(lines[0]["data"]["messages"]) == 2
    assert lines[0]["data"]["messages"][0]["role"] == "assistant"
    assert lines[0]["data"]["messages"][1]["role"] == "user"


def test_rpc_mode_get_messages_returns_error_when_session_context_is_invalid() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenMessageGetterSession(FakeSession):
        def get_session_context(
            self,
        ):  # pragma: no cover - defensive path exercised by test
            return object()

    session = BrokenMessageGetterSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "messages", "type": "get_messages"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        # simulate an upstream corruption that bypasses expected list shapes
        mode._get_session_messages = lambda _session: "invalid"
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "messages",
            "type": "response",
            "command": "get_messages",
            "success": False,
            "error": "Message log returned an invalid response.",
        },
    ]


def test_rpc_mode_command_catalog_preserves_the_complete_legacy_surface() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    mode = RpcMode(
        runtime=FakeRuntime(FakeSession(session_id="session-a", cwd="/tmp/project")),
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert mode._command_router.command_types == frozenset(
        {
            "abort",
            "abort_bash",
            "abort_retry",
            "bash",
            "check_package_updates",
            "clone",
            "compact",
            "cycle_model",
            "cycle_thinking_level",
            "execute_command",
            "export_html",
            "extension_ui_response",
            "follow_up",
            "fork",
            "get_available_models",
            "get_command_completions",
            "get_commands",
            "get_diagnostics",
            "get_diagnostics_summary",
            "get_extension_ui_state",
            "get_fork_messages",
            "get_last_assistant_text",
            "get_last_error_report",
            "get_messages",
            "get_packages",
            "get_session_diagnostics",
            "get_session_diagnostics_summary",
            "get_session_stats",
            "get_state",
            "install_package",
            "list_sessions",
            "materialize_package",
            "new_session",
            "prompt",
            "remove_package",
            "set_active_tools",
            "set_auto_compaction",
            "set_auto_retry",
            "set_follow_up_mode",
            "set_model",
            "set_session_name",
            "set_steering_mode",
            "set_thinking_level",
            "steer",
            "switch_session",
            "uninstall_package",
            "update_package",
            "update_packages",
        }
    )


def test_rpc_mode_get_state_returns_error_when_state_serialization_fails() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenStateSession(FakeSession):
        def get_state(self):  # type: ignore[override]
            raise RuntimeError("state unavailable")

    session = BrokenStateSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "state",
            "type": "response",
            "command": "get_state",
            "success": False,
            "error": "Failed to serialize session state.",
        },
    ]


def test_rpc_mode_get_state_uses_standard_session_state() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "state", "type": "get_state"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "state",
            "type": "response",
            "command": "get_state",
            "success": True,
            "data": {
                "sessionId": "session-a",
                "model": None,
                "isStreaming": False,
                "isCompacting": False,
                "steeringMode": "one-at-a-time",
                "followUpMode": "one-at-a-time",
                "autoCompactionEnabled": True,
                "messageCount": 0,
                "pendingMessageCount": 0,
                "thinkingLevel": "off",
                "sessionFile": "/tmp/project/session-a.jsonl",
            },
        },
    ]


def test_rpc_mode_get_session_stats_handles_query_errors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenStatsSession(FakeSession):
        def get_session_stats(self) -> object:
            raise RuntimeError("stats failed")

    session = BrokenStatsSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "stats", "type": "get_session_stats"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "stats",
            "type": "response",
            "command": "get_session_stats",
            "success": False,
            "error": "Failed to query session stats: stats failed",
        },
    ]


def test_rpc_mode_get_session_stats_prefers_public_snake_case_payload() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class SnakeCaseStatsSession(FakeSession):
        def get_session_stats(self) -> dict[str, object]:
            return {"sessionId": self.session_id, "customCounter": 3}

    session = SnakeCaseStatsSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "stats", "type": "get_session_stats"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "stats",
            "type": "response",
            "command": "get_session_stats",
            "success": True,
            "data": {"sessionId": "session-a", "customCounter": 3},
        },
    ]


def test_rpc_mode_get_session_stats_returns_error_when_payload_invalid() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidStatsSession(FakeSession):
        def get_session_stats(self) -> object:
            return ["invalid"]

    session = InvalidStatsSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "stats", "type": "get_session_stats"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "stats",
            "type": "response",
            "command": "get_session_stats",
            "success": False,
            "error": "Session stats returned an invalid response.",
        },
    ]


def test_rpc_mode_set_model_reports_model_registry_errors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenModelSession(FakeSession):
        def get_available_models(self):
            raise RuntimeError("model registry failed")

    session = BrokenModelSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {
                "id": "model",
                "type": "set_model",
                "provider": "faux",
                "endpointId": "test-endpoint",
                "modelId": "alpha",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "model",
            "type": "response",
            "command": "set_model",
            "success": False,
            "error": "Failed to query model registry: model registry failed",
        }
    ]


def test_rpc_mode_set_model_reports_invalid_model_registry_response_type() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidTypeSession(FakeSession):
        def get_available_models(self):
            return {"provider": "faux", "modelId": "alpha"}

    session = InvalidTypeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {
                "id": "model",
                "type": "set_model",
                "provider": "faux",
                "endpointId": "test-endpoint",
                "modelId": "alpha",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_model_calls == []
    assert _parse_jsonl(stdout) == [
        {
            "id": "model",
            "type": "response",
            "command": "set_model",
            "success": False,
            "error": "Model registry returned an invalid response.",
        }
    ]


def test_rpc_mode_set_active_tools_reports_setter_errors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenToolsSession(FakeSession):
        async def set_active_tools(self, tool_names: list[str]) -> None:
            raise RuntimeError("tool configuration failed")

    session = BrokenToolsSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "tools", "type": "set_active_tools", "toolNames": ["bash"]})
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "tools",
            "type": "response",
            "command": "set_active_tools",
            "success": False,
            "error": "Failed to set active tools: tool configuration failed",
        }
    ]


def test_rpc_mode_compact_reports_execution_errors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenCompactSession(FakeSession):
        async def compact(self, custom_instructions: str | None = None):
            del custom_instructions
            raise RuntimeError("compact failed")

    session = BrokenCompactSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "compact", "type": "compact"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "compact",
            "type": "response",
            "command": "compact",
            "success": False,
            "error": "Failed to compact session: compact failed",
        }
    ]


def test_rpc_mode_get_fork_messages_returns_error_when_payload_invalid() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidForkMessagesSession(FakeSession):
        def get_user_messages_for_forking(self) -> object:
            return {"messages": []}

    session = InvalidForkMessagesSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "fork-messages", "type": "get_fork_messages"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "fork-messages",
            "type": "response",
            "command": "get_fork_messages",
            "success": False,
            "error": "Fork messages returned an invalid response.",
        },
    ]


def test_rpc_mode_get_last_assistant_text_handles_extraction_errors() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class BrokenLastAssistantTextSession(FakeSession):
        def get_last_assistant_text(self) -> str | None:
            raise RuntimeError("assistant extraction failed")

    session = BrokenLastAssistantTextSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "last", "type": "get_last_assistant_text"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "last",
            "type": "response",
            "command": "get_last_assistant_text",
            "success": False,
            "error": "Failed to read last assistant text: assistant extraction failed",
        },
    ]


def test_rpc_mode_get_last_assistant_text_uses_standard_session_method() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class StandardLastAssistantSession(FakeSession):
        def get_last_assistant_text(self):
            return "latest"

    session = StandardLastAssistantSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps({"id": "last", "type": "get_last_assistant_text"}) + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout)[0]["data"] == {"text": "latest"}


def test_rpc_mode_supports_cycle_thinking_and_auto_compaction_commands() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.set_thinking_level("low")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "cycle", "type": "cycle_thinking_level"}),
                json.dumps(
                    {
                        "id": "compact-setting",
                        "type": "set_auto_compaction",
                        "enabled": False,
                    }
                ),
            ]
        )
        + "\n"
    )
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_thinking_level_calls == ["low", "medium"]
    assert session.set_auto_compaction_calls == [False]

    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "cycle",
        "type": "response",
        "command": "cycle_thinking_level",
        "success": True,
        "data": {"level": "medium"},
    }
    assert lines[1] == {
        "id": "compact-setting",
        "type": "response",
        "command": "set_auto_compaction",
        "success": True,
    }


def test_rpc_mode_supports_cycle_model_command() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        [
            ModelSelection(
                endpoint_id="coding", provider="faux", model_id="alpha"
            ),
            ModelSelection(
                endpoint_id="coding", provider="openai", model_id="gpt-5"
            ),
        ],
        resolved_models={
            ("faux", "coding", "alpha"): Model(
                id="alpha",
                provider="faux",
                endpoint="coding",
                name="Faux Alpha",
                capabilities=Capabilities(
                    input=("text",),
                    context_window=128_000,
                    max_tokens=8_192,
                    reasoning=False,
                ),
                pricing=Pricing(input=1, output=2, cache_read=0.1, cache_write=0.2),
            ),
            ("openai", "coding", "gpt-5"): Model(
                id="gpt-5",
                provider="openai",
                endpoint="coding",
                name="GPT-5",
                capabilities=Capabilities(
                    input=("text", "image"),
                    context_window=400_000,
                    max_tokens=16_384,
                    reasoning=True,
                ),
                pricing=Pricing(input=5, output=15, cache_read=0.5, cache_write=0.8),
                adapter=OpenAICompletionsConfig(reasoning_effort=True),
            ),
        },
        endpoints={
            ("faux", "coding"): Endpoint(
                id="coding",
                api="openai-completions",
                provider="faux",
                base_url="https://api.faux.test/v1",
            ),
            ("openai", "coding"): Endpoint(
                id="coding",
                api="openai-responses",
                provider="openai",
                base_url="https://api.openai.test/v1",
            ),
        },
    )
    asyncio.run(
        session.set_model(
            ModelSelection(
                endpoint_id="coding", provider="faux", model_id="alpha"
            )
        )
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "cycle-model", "type": "cycle_model"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert session.set_model_calls == [
        ModelSelection(endpoint_id="coding", provider="faux", model_id="alpha"),
        ModelSelection(
            endpoint_id="coding", provider="openai", model_id="gpt-5"
        ),
    ]

    assert _parse_jsonl(stdout) == [
        {
            "id": "cycle-model",
            "type": "response",
            "command": "cycle_model",
            "success": True,
            "data": {
                "model": {
                    "provider": "openai",
                    "endpointId": "coding",
                    "id": "gpt-5",
                    "name": "GPT-5",
                    "api": "openai-responses",
                    "baseUrl": "https://api.openai.test/v1",
                    "input": ["text", "image"],
                    "contextWindow": 400_000,
                    "maxTokens": 16_384,
                    "reasoning": True,
                    "cost": {
                        "input": 5,
                        "output": 15,
                        "cacheRead": 0.5,
                        "cacheWrite": 0.8,
                    },
                },
                "thinkingLevel": "off",
                "isScoped": False,
            },
        }
    ]


def test_rpc_mode_cycle_model_returns_explicit_null_data_when_no_models_exist() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "cycle-model", "type": "cycle_model"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "cycle-model",
            "type": "response",
            "command": "cycle_model",
            "success": True,
            "data": None,
        }
    ]


def test_rpc_mode_cycle_model_reports_invalid_model_registry_response_type() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    class InvalidTypeSession(FakeSession):
        def get_available_models(self):
            return "not-a-list"

    session = InvalidTypeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "cycle-model", "type": "cycle_model"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    assert _parse_jsonl(stdout) == [
        {
            "id": "cycle-model",
            "type": "response",
            "command": "cycle_model",
            "success": False,
            "error": "Model registry returned an invalid response.",
        }
    ]
