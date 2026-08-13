from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path

from loushang.ai.model import ModelSelection
from loushang.ai.model.domain import (
    Capabilities,
    Endpoint,
    Model,
    OpenAICompletionsConfig,
    Pricing,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from tests.coding.rpc_support import (
    FakeModelRegistry,
    FakeRuntime,
    FakeSession,
    _assistant_message,
    _parse_jsonl,
)


def test_rpc_mode_applies_control_commands_to_active_session() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        resolved_models={
            ("faux", "coding", "beta"): Model(
                id="beta",
                provider="faux",
                endpoint="coding",
                name="Faux Beta",
                capabilities=Capabilities(
                    input=("text",),
                    context_window=256_000,
                    max_tokens=12_288,
                    reasoning=True,
                ),
                pricing=Pricing(input=3, output=4, cache_read=0.3, cache_write=0.4),
                adapter=OpenAICompletionsConfig(reasoning_effort=True),
            )
        },
        endpoints={
            ("faux", "coding"): Endpoint(
                id="coding",
                api="openai-completions",
                provider="faux",
                base_url="https://api.faux.test/v1",
            )
        },
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "steer", "type": "steer", "message": "watch this"}),
                json.dumps(
                    {"id": "follow", "type": "follow_up", "message": "continue"}
                ),
                json.dumps({"id": "abort", "type": "abort"}),
                json.dumps(
                    {
                        "id": "model",
                        "type": "set_model",
                        "provider": "faux",
                        "endpointId": "coding",
                        "modelId": "beta",
                    }
                ),
                json.dumps(
                    {
                        "id": "tools",
                        "type": "set_active_tools",
                        "toolNames": ["bash", "read"],
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

    assert session.steer_calls == [("watch this", None)]
    assert session.follow_up_calls == [("continue", None)]
    assert session.abort_calls == 1
    assert session.set_model_calls == [
        ModelSelection(endpoint_id="coding", provider="faux", model_id="beta")
    ]
    assert session.set_active_tools_calls == [["bash", "read"]]

    lines = _parse_jsonl(stdout)
    assert lines[3] == {
        "id": "model",
        "type": "response",
        "command": "set_model",
        "success": True,
        "data": {
            "provider": "faux",
            "endpointId": "coding",
            "id": "beta",
            "name": "Faux Beta",
            "api": "openai-completions",
            "baseUrl": "https://api.faux.test/v1",
            "input": ["text"],
            "contextWindow": 256_000,
            "maxTokens": 12_288,
            "reasoning": True,
            "cost": {
                "input": 3,
                "output": 4,
                "cacheRead": 0.3,
                "cacheWrite": 0.4,
            },
        },
    }
    commands = [line["command"] for line in lines]
    assert commands == ["steer", "follow_up", "abort", "set_model", "set_active_tools"]


def test_rpc_mode_set_model_rejects_models_outside_available_list() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.model_registry = FakeModelRegistry(
        [ModelSelection(endpoint_id="test-endpoint", provider="faux", model_id="alpha")]
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(
        json.dumps(
            {
                "id": "model",
                "type": "set_model",
                "provider": "faux",
                "endpointId": "test-endpoint",
                "modelId": "missing",
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
            "error": "Model not found: faux:test-endpoint:missing",
        }
    ]


def test_rpc_mode_passes_images_to_steer_and_follow_up_commands() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    image = {"type": "image", "data": "abc123", "mimeType": "image/png"}
    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "steer",
                        "type": "steer",
                        "message": "watch",
                        "images": [image],
                    }
                ),
                json.dumps(
                    {
                        "id": "follow",
                        "type": "follow_up",
                        "message": "later",
                        "images": [image],
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

    assert session.steer_calls == [("watch", [image])]
    assert session.follow_up_calls == [("later", [image])]
    assert _parse_jsonl(stdout) == [
        {"id": "steer", "type": "response", "command": "steer", "success": True},
        {"id": "follow", "type": "response", "command": "follow_up", "success": True},
    ]


def test_rpc_mode_supports_thinking_stats_retry_compact_and_export_commands() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(
        session_id="session-a", session_name="Alpha", cwd="/tmp/project"
    )
    asyncio.run(session.set_active_tools(["bash"]))
    asyncio.run(
        session.set_model(
            ModelSelection(
                endpoint_id="test-endpoint", provider="faux", model_id="alpha"
            )
        )
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "think", "type": "set_thinking_level", "level": "high"}
                ),
                json.dumps({"id": "stats", "type": "get_session_stats"}),
                json.dumps(
                    {"id": "retry-on", "type": "set_auto_retry", "enabled": False}
                ),
                json.dumps({"id": "retry-off", "type": "abort_retry"}),
                json.dumps({"id": "compact", "type": "compact"}),
                json.dumps(
                    {
                        "id": "export",
                        "type": "export_html",
                        "outputPath": "/tmp/exported.html",
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

    assert session.set_thinking_level_calls == ["high"]
    assert session.set_auto_retry_calls == [False]
    assert session.abort_retry_calls == 1
    assert session.compact_calls == [None]
    assert session.export_to_html_calls == ["/tmp/exported.html"]

    lines = _parse_jsonl(stdout)
    assert lines[0]["command"] == "set_thinking_level"
    assert lines[0] == {
        "id": "think",
        "type": "response",
        "command": "set_thinking_level",
        "success": True,
    }

    assert lines[1]["command"] == "get_session_stats"
    assert lines[1]["data"]["sessionId"] == "session-a"
    assert lines[1]["data"]["lastModelSelection"] == {
        "provider": "faux",
        "modelId": "alpha",
    }
    assert lines[1]["data"]["contextUsage"]["estimatedContextTokens"] == 123

    assert lines[2] == {
        "id": "retry-on",
        "type": "response",
        "command": "set_auto_retry",
        "success": True,
    }
    assert lines[3] == {
        "id": "retry-off",
        "type": "response",
        "command": "abort_retry",
        "success": True,
    }

    assert lines[4]["command"] == "compact"
    assert lines[4]["data"] == {
        "summary": "compacted",
        "firstKeptEntryId": "entry-1",
        "tokensBefore": 42,
        "details": {"preserved": 3},
    }

    assert lines[5] == {
        "id": "export",
        "type": "response",
        "command": "export_html",
        "success": True,
        "data": {"path": "/tmp/exported.html"},
    }


def test_rpc_mode_passes_custom_instructions_to_compact_command() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "camel",
                        "type": "compact",
                        "customInstructions": "keep API details",
                    }
                ),
                json.dumps(
                    {
                        "id": "snake",
                        "type": "compact",
                        "custom_instructions": "keep tests",
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

    assert session.compact_calls == ["keep API details", "keep tests"]
    assert [line["command"] for line in _parse_jsonl(stdout)] == ["compact", "compact"]


def test_rpc_mode_supports_queue_model_name_and_command_queries() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    assistant = _assistant_message("latest answer")
    session = FakeSession(
        session_id="session-a",
        session_name="Alpha",
        cwd="/tmp/project",
        messages=[assistant],
    )
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
                adapter=OpenAICompletionsConfig(reasoning_effort=False),
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
    session.resource_bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="review",
                source_path=Path("/tmp/project/prompts/review.md"),
                text="Review prompt",
            )
        ],
        skills=[
            SkillDescriptor(
                name="debug",
                source_path=Path("/tmp/project/skills/debug/SKILL.md"),
                content="# Debug",
            )
        ],
    )
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps(
                    {"id": "steering-mode", "type": "set_steering_mode", "mode": "all"}
                ),
                json.dumps(
                    {"id": "follow-mode", "type": "set_follow_up_mode", "mode": "all"}
                ),
                json.dumps({"id": "models", "type": "get_available_models"}),
                json.dumps(
                    {"id": "rename", "type": "set_session_name", "name": "Renamed"}
                ),
                json.dumps({"id": "last", "type": "get_last_assistant_text"}),
                json.dumps({"id": "commands", "type": "get_commands"}),
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

    assert session.set_steering_mode_calls == ["all"]
    assert session.set_follow_up_mode_calls == ["all"]
    assert session.set_session_name_calls == ["Renamed"]
    assert session.session_manager.session_info_calls == ["Renamed"]

    lines = _parse_jsonl(stdout)
    assert lines[0] == {
        "id": "steering-mode",
        "type": "response",
        "command": "set_steering_mode",
        "success": True,
    }
    assert lines[1] == {
        "id": "follow-mode",
        "type": "response",
        "command": "set_follow_up_mode",
        "success": True,
    }
    assert lines[2] == {
        "id": "models",
        "type": "response",
        "command": "get_available_models",
        "success": True,
        "data": {
            "models": [
                {
                    "provider": "faux",
                    "endpointId": "coding",
                    "id": "alpha",
                    "name": "Faux Alpha",
                    "api": "openai-completions",
                    "baseUrl": "https://api.faux.test/v1",
                    "input": ["text"],
                    "contextWindow": 128_000,
                    "maxTokens": 8_192,
                    "reasoning": False,
                    "cost": {
                        "input": 1,
                        "output": 2,
                        "cacheRead": 0.1,
                        "cacheWrite": 0.2,
                    },
                },
                {
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
            ]
        },
    }
    assert lines[3] == {
        "id": "rename",
        "type": "response",
        "command": "set_session_name",
        "success": True,
    }
    assert lines[4] == {
        "id": "last",
        "type": "response",
        "command": "get_last_assistant_text",
        "success": True,
        "data": {"text": "latest answer"},
    }
    assert lines[5] == {
        "id": "commands",
        "type": "response",
        "command": "get_commands",
        "success": True,
        "data": {
            "commands": [
                {
                    "name": "/review",
                    "description": None,
                    "source": "prompt",
                    "sourceInfo": {
                        "path": "/tmp/project/prompts/review.md",
                        "source": "filesystem",
                        "scope": "project",
                        "origin": "top-level",
                        "baseDir": "/tmp/project/prompts",
                    },
                },
                {
                    "name": "/skill:debug",
                    "description": None,
                    "source": "skill",
                    "sourceInfo": {
                        "path": "/tmp/project/skills/debug/SKILL.md",
                        "source": "filesystem",
                        "scope": "project",
                        "origin": "top-level",
                        "baseDir": "/tmp/project/skills/debug",
                    },
                },
            ]
        },
    }


def test_rpc_mode_set_session_name_trims_and_rejects_blank_names() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    runtime = FakeRuntime(session)
    stdin = StringIO(
        "\n".join(
            [
                json.dumps({"id": "blank", "type": "set_session_name", "name": "   "}),
                json.dumps(
                    {"id": "trimmed", "type": "set_session_name", "name": "  Renamed  "}
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

    assert session.set_session_name_calls == ["Renamed"]
    assert _parse_jsonl(stdout) == [
        {
            "id": "blank",
            "type": "response",
            "command": "set_session_name",
            "success": False,
            "error": "Session name cannot be empty",
        },
        {
            "id": "trimmed",
            "type": "response",
            "command": "set_session_name",
            "success": True,
        },
    ]


def test_rpc_mode_get_commands_includes_extension_prompt_and_skill_entries() -> None:
    from loushang.harness.host.rpc import RpcHost as RpcMode

    session = FakeSession(session_id="session-a", cwd="/tmp/project")
    session.command_entries = [
        {
            "name": "deploy",
            "description": "Deploy the project",
            "source": "extension",
            "source_info": {"path": "/tmp/project/extensions/deploy-ext.py"},
        },
        {
            "name": "plan",
            "description": "Use a planning workflow before editing.",
            "source": "prompt",
            "source_info": {"path": "/tmp/project/prompts/plan.md"},
        },
        {
            "name": "skill:debugging",
            "description": "Check the failing path first.",
            "source": "skill",
            "source_info": {"path": "/tmp/project/skills/debugging/SKILL.md"},
        },
    ]
    runtime = FakeRuntime(session)
    stdin = StringIO(json.dumps({"id": "commands", "type": "get_commands"}) + "\n")
    stdout = StringIO()

    async def scenario() -> None:
        mode = RpcMode(runtime=runtime, stdin=stdin, stdout=stdout)
        exit_code = await mode.run()
        assert exit_code == 0

    asyncio.run(scenario())

    lines = _parse_jsonl(stdout)
    assert lines == [
        {
            "id": "commands",
            "type": "response",
            "command": "get_commands",
            "success": True,
            "data": {
                "commands": [
                    {
                        "name": "deploy",
                        "description": "Deploy the project",
                        "source": "extension",
                        "sourceInfo": {
                            "path": "/tmp/project/extensions/deploy-ext.py",
                            "source": "filesystem",
                            "scope": "project",
                            "origin": "top-level",
                            "baseDir": "/tmp/project/extensions",
                        },
                    },
                    {
                        "name": "plan",
                        "description": "Use a planning workflow before editing.",
                        "source": "prompt",
                        "sourceInfo": {
                            "path": "/tmp/project/prompts/plan.md",
                            "source": "filesystem",
                            "scope": "project",
                            "origin": "top-level",
                            "baseDir": "/tmp/project/prompts",
                        },
                    },
                    {
                        "name": "skill:debugging",
                        "description": "Check the failing path first.",
                        "source": "skill",
                        "sourceInfo": {
                            "path": "/tmp/project/skills/debugging/SKILL.md",
                            "source": "filesystem",
                            "scope": "project",
                            "origin": "top-level",
                            "baseDir": "/tmp/project/skills/debugging",
                        },
                    },
                ]
            },
        }
    ]
