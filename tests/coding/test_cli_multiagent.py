from __future__ import annotations

import asyncio
import json
from functools import partial
from io import StringIO

import pytest

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import (
    Capabilities,
    Endpoint,
    Model,
    ModelSelection,
    Provider,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.coding.bootstrap import (
    create_agent_session_runtime,
    create_services,
)
from loushang.coding.cli.__main__ import (
    build_builtin_tool_registry,
    run_cli,
)
from loushang.coding.cli.multiagent import run_coding_multiagent_command
from loushang.harness.cli.multiagent import (
    MultiAgentCliUsageError,
    MultiAgentRunCommand,
    extract_multiagent_argv,
    parse_multiagent_command,
)


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _registry(model: Model) -> ModelRegistry:
    endpoint = Endpoint(
        id=model.endpoint_id,
        provider=model.provider_id,
        api=model.api or model.endpoint_id,
        models={model.id: model},
    )
    provider = Provider(
        id=model.provider_id,
        endpoints={endpoint.id: endpoint},
    )
    return ModelRegistry.from_providers({provider.id: provider})


def _assistant(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=10,
            output=5,
            cache_read=2,
            cache_write=0,
            total_tokens=17,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _stream(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "text_start", "content_index": 0, "partial": message})
    stream.push(
        {
            "type": "text_delta",
            "content_index": 0,
            "delta": message.content[0].text,
            "partial": message,
        }
    )
    stream.push(
        {
            "type": "text_end",
            "content_index": 0,
            "content": message.content[0].text,
            "partial": message,
        }
    )
    stream.push(
        {
            "type": "done",
            "reason": message.stop_reason,
            "message": message,
        }
    )
    return stream


def test_extracts_long_and_short_multiagent_commands_with_leading_cwd() -> None:
    assert extract_multiagent_argv(("ma", "recipes")) == ("recipes",)
    assert extract_multiagent_argv(("multiagent", "run", "debate")) == (
        "run",
        "debate",
    )
    assert extract_multiagent_argv(("--cwd", "/repo", "ma", "recipes")) == (
        "recipes",
        "--cwd",
        "/repo",
    )
    assert extract_multiagent_argv(("hello",)) is None


def test_parses_short_generic_recipe_options_without_a_format_prefix() -> None:
    command = parse_multiagent_command(
        (
            "run",
            "parallel-review",
            "--prompt",
            "Review it.",
            "--count",
            "3",
            "--agent",
            "synthesizer=faux/faux-model",
            "--format",
            "json",
        )
    )

    assert isinstance(command, MultiAgentRunCommand)
    assert command.count == 3
    assert command.agent_models == {"synthesizer": "faux/faux-model"}
    assert command.output_format == "json"


@pytest.mark.parametrize(
    "option",
    (
        ("--count", "0"),
        ("--max-parallel", "0"),
        ("--timeout", "0"),
    ),
)
def test_rejects_non_positive_recipe_limits(option: tuple[str, str]) -> None:
    with pytest.raises(MultiAgentCliUsageError, match="must be positive"):
        parse_multiagent_command(
            (
                "run",
                "parallel-review",
                "--prompt",
                "Review it.",
                *option,
            )
        )


def test_run_cli_routes_ma_before_the_standard_agent_parser(tmp_path) -> None:
    observed: list[tuple[str, ...]] = []

    async def runner(argv, **_kwargs):
        observed.append(tuple(argv))
        return 17

    result = asyncio.run(
        run_cli(
            ("ma", "recipes"),
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=StringIO(),
            multiagent_runner=runner,
        )
    )

    assert result == 17
    assert observed == [("recipes",)]


def test_real_parallel_review_uses_non_persistent_coding_children_and_full_fan_in(
    tmp_path,
) -> None:
    calls: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        prompt = context.messages[-1].content[0].text
        calls.append(prompt)
        if prompt.startswith("Synthesize"):
            return _stream(_assistant("Final synthesized recommendation."))
        return _stream(_assistant(f"Independent finding {len(calls)}."))

    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        attachment = project / "design.md"
        attachment.write_text("Design evidence.", encoding="utf-8")
        model = _model()
        services = create_services(
            ai_model_registry=_registry(model),
            default_model=ModelSelection(
                endpoint_id="anthropic-messages",
                provider="faux",
                model_id="faux-model",
            ),
        )
        stdout = StringIO()
        stderr = StringIO()

        result = await run_coding_multiagent_command(
            (
                "run",
                "parallel-review",
                "--prompt",
                "Review this architecture.",
                "--count",
                "2",
                "--format",
                "json",
                "@design.md",
            ),
            stdout=stdout,
            stderr=stderr,
            cwd=project,
            services=services,
            build_services=lambda _cwd: services,
            build_tool_registry=build_builtin_tool_registry,
            runtime_builder=partial(
                create_agent_session_runtime,
                stream_fn=stream_fn,
            ),
        )

        assert result == 0, stderr.getvalue()
        payload = json.loads(stdout.getvalue())
        assert payload["recipe"] == "parallel-review"
        assert payload["status"] == "completed"
        assert payload["final_message"] == "Final synthesized recommendation."
        assert [item["path"] for item in payload["agents"]] == [
            "/root/reviewer-1",
            "/root/reviewer-2",
            "/root/synthesizer",
        ]
        assert len(calls) == 3
        assert "Design evidence." in calls[0]
        assert "Independent finding 1." in calls[2]
        assert "Independent finding 2." in calls[2]
        session_dir = project / ".loushang" / "sessions"
        assert not tuple(session_dir.glob("*.jsonl"))

    asyncio.run(scenario())


def test_real_debate_applies_per_role_model_override(tmp_path) -> None:
    selected: list[str] = []

    async def stream_fn(model, context, options=None):
        del context, options
        selected.append(f"{model.provider_id}/{model.id}")
        return _stream(_assistant(f"Round {len(selected)}."))

    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        model = _model()
        registry = _registry(model)
        services = create_services(
            ai_model_registry=registry,
            default_model=ModelSelection(
                endpoint_id="anthropic-messages",
                provider="faux",
                model_id="faux-model",
            ),
        )
        stdout = StringIO()
        stderr = StringIO()

        result = await run_coding_multiagent_command(
            (
                "run",
                "debate",
                "--prompt",
                "Adopt this design?",
                "--agent",
                "critic=faux/faux-model",
            ),
            stdout=stdout,
            stderr=stderr,
            cwd=project,
            services=services,
            build_services=lambda _cwd: services,
            build_tool_registry=build_builtin_tool_registry,
            runtime_builder=partial(
                create_agent_session_runtime,
                stream_fn=stream_fn,
            ),
        )

        assert result == 0, stderr.getvalue()
        assert selected == [
            "faux/faux-model",
            "faux/faux-model",
            "faux/faux-model",
        ]
        assert "Result\nRound 3." in stdout.getvalue()

    asyncio.run(scenario())


def test_scripted_provider_exercises_the_real_coding_runtime_without_credentials(
    tmp_path,
) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        services = create_services()
        stdout = StringIO()
        stderr = StringIO()

        result = await run_coding_multiagent_command(
            (
                "run",
                "debate",
                "--provider",
                "scripted",
                "--prompt",
                "Adopt this design?",
            ),
            stdout=stdout,
            stderr=stderr,
            cwd=project,
            services=services,
            build_services=lambda _cwd: services,
            build_tool_registry=build_builtin_tool_registry,
        )

        assert result == 0, stderr.getvalue()
        assert "Scripted judge: conditionally adopt" in stdout.getvalue()
        assert not tuple((project / ".loushang" / "sessions").glob("*.jsonl"))

    asyncio.run(scenario())
