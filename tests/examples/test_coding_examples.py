from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_minimal_coding_example_reports_agent_error_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(
        Path("examples/coding/01_minimal.py"),
        "examples_coding_01_minimal",
    )
    summary_called = False

    class _FakeSessionManager:
        def get_cwd(self) -> str:
            return "/tmp/project"

    class _FakeAgent:
        error_message = "missing api key"

    class _FakeSession:
        def __init__(self) -> None:
            self.agent = _FakeAgent()
            self.session_manager = _FakeSessionManager()

        async def prompt(self, user_input: str) -> None:
            assert user_input

    monkeypatch.setattr(module, "CalcTool", lambda: object())
    monkeypatch.setattr(module, "build_kimi_model", lambda: object())
    monkeypatch.setattr(
        module,
        "describe_model",
        lambda model: {
            "provider": "kimi-code",
            "model": "kimi-for-coding",
            "api": "anthropic-messages",
            "base_url": "https://api.kimi.com/coding",
        },
    )
    monkeypatch.setattr(module, "create_kimi_session", lambda **kwargs: _FakeSession())
    monkeypatch.setattr(module, "attach_stream_printer", lambda session: None)

    def _mark_summary_called(session) -> None:
        nonlocal summary_called
        summary_called = True

    monkeypatch.setattr(module, "print_message_summary", _mark_summary_called)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(module.main())

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "missing api key" in captured.err
    assert summary_called is False


def test_weekly_usage_ledger_preserves_unknown_cost() -> None:
    from loushang.ai.types import Usage

    module = _load_module(
        Path("examples/coding/23_kimi_weekly_usage_ledger.py"),
        "examples_coding_23_kimi_weekly_usage_ledger",
    )
    response = SimpleNamespace(
        usage=Usage(
            input=1,
            output=2,
            cache_read=0,
            cache_write=0,
            total_tokens=3,
            cost=None,
        )
    )
    model = SimpleNamespace(pricing=None)

    payload = module._usage_from_response(response, model)

    assert payload.cost_input is None
    assert payload.cost_output is None
    assert payload.cost_cache_read is None
    assert payload.cost_cache_write is None
    assert payload.cost_total is None


def test_weekly_usage_ledger_preserves_known_cost() -> None:
    from loushang.ai.model import Pricing
    from loushang.ai.types import Usage

    module = _load_module(
        Path("examples/coding/23_kimi_weekly_usage_ledger.py"),
        "examples_coding_23_kimi_weekly_usage_ledger_known",
    )
    response = SimpleNamespace(
        usage=Usage(
            input=1000,
            output=2000,
            cache_read=3000,
            cache_write=4000,
            total_tokens=10000,
            cost=None,
        )
    )
    model = SimpleNamespace(
        pricing=Pricing(input=1.0, output=2.0, cache_read=0.5, cache_write=0.25)
    )

    payload = module._usage_from_response(response, model)

    assert payload.cost_input == pytest.approx(0.001)
    assert payload.cost_output == pytest.approx(0.004)
    assert payload.cost_cache_read == pytest.approx(0.0015)
    assert payload.cost_cache_write == pytest.approx(0.001)
    assert payload.cost_total == pytest.approx(0.0075)


def test_kimi_code_examples_use_the_builtin_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOUSHANG_EXAMPLES_MODEL_CATALOG", raising=False)
    monkeypatch.delenv("LOUSHANG_EXAMPLES_ARTIFACT_ROOT", raising=False)
    module = _load_module(
        Path("examples/coding/_support.py"),
        "examples_coding_support_builtin_catalog",
    )

    assert module._resolve_model_catalog() is None
    for endpoint_id in ("kimi-code-openai", "kimi-code-anthropic"):
        model = module.build_kimi_model(endpoint_id=endpoint_id)
        assert model.provider_id == "kimi-code"
        assert model.endpoint_id == endpoint_id
        assert model.id == "kimi-for-coding"


def test_usage_inspect_example_marks_unknown_cost(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage

    module = _load_module(
        Path("examples/coding/22_usage_inspect.py"),
        "examples_coding_22_usage_inspect",
    )

    async def _complete(model, context):
        assert model
        assert context
        return AssistantMessage(
            role="assistant",
            content=[TextPart(type="text", text="ok")],
            api="anthropic-messages",
            provider="kimi-code",
            endpoint="kimi-code-anthropic",
            model="kimi-for-coding",
            response_id=None,
            usage=Usage(
                input=1,
                output=2,
                cache_read=0,
                cache_write=0,
                total_tokens=3,
                cost=None,
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=123.0,
        )

    monkeypatch.setattr(sys, "argv", ["22_usage_inspect.py"])
    monkeypatch.setattr(module, "_resolve_model_catalog", lambda: None)
    monkeypatch.setattr(
        module, "build_kimi_model", lambda **kwargs: SimpleNamespace(pricing=None)
    )
    monkeypatch.setattr(
        module,
        "describe_model",
        lambda model: {
            "provider": "kimi-code",
            "endpoint": "kimi-code-anthropic",
            "api": "anthropic-messages",
            "base_url": "https://api.kimi.com/coding",
            "model": "kimi-for-coding",
        },
    )
    monkeypatch.setattr(module, "complete", _complete)

    assert asyncio.run(module.main()) == 0

    output = capsys.readouterr().out
    message_end = next(
        line for line in output.splitlines() if line.startswith("message.end: ")
    )
    assert json.loads(message_end.removeprefix("message.end: "))["cost"] == {
        "known": False
    }
    assert "cost: {'known': False}" in output


def test_runtime_capability_replacement_extension_example_runs_offline() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/coding/extensions/06_runtime_capability_replacement.py",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "Selected source: extension" in completed.stdout
    assert "Selected layer: extension:examples.side-question" in completed.stdout
    assert (
        "Implementation: "
        "extension:examples.side-question:interaction.side_question:demo"
        in completed.stdout
    )
    assert "Answer: extension:What is the current status?" in completed.stdout
    assert (
        "Lifecycle: create -> bind -> ask:What is the current status? -> dispose"
        in (completed.stdout)
    )
