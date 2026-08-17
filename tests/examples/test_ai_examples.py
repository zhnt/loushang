from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.ai.model import load_model_registry_from_file

REPO_ROOT = Path(__file__).resolve().parents[2]
TOP_LEVEL_OFFLINE_EXAMPLES = sorted(
    (REPO_ROOT / "examples/ai").glob("[0-9][0-9]_*.py")
) + [REPO_ROOT / "examples/ai/custom_model_file.py"]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _loushang_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "loushang" or node.module.startswith("loushang."):
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "loushang" or alias.name.startswith("loushang."):
                    modules.append(alias.name)
    return modules


def test_top_level_ai_examples_run_offline(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for key in [
        "ANTHROPIC_API_KEY",
        "BAIDU_QIANFAN_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "OPENAI_API_KEY",
        "QIANFAN_API_KEY",
        "STEPFUN_API_KEY",
        "STEP_API_KEY",
    ]:
        env.pop(key, None)

    assert [path.name for path in TOP_LEVEL_OFFLINE_EXAMPLES] == [
        "01_complete.py",
        "02_stream.py",
        "03_typed_context.py",
        "04_tools.py",
        "05_parallel_tools.py",
        "06_reasoning.py",
        "07_structured_output.py",
        "08_image_input.py",
        "09_errors_retry.py",
        "10_usage.py",
        "11_provider_matrix.py",
        "12_provider_smoke.py",
        "custom_model_file.py",
    ]

    for path in TOP_LEVEL_OFFLINE_EXAMPLES:
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert completed.returncode == 0, (path, completed.stdout, completed.stderr)
        assert completed.stdout.strip(), path


def test_top_level_ai_examples_stay_on_public_import_boundary() -> None:
    base_allowed = {"loushang.ai", "loushang.ai.tool"}
    custom_model_file_allowed = {"loushang.ai.model"}

    for path in TOP_LEVEL_OFFLINE_EXAMPLES:
        allowed = set(base_allowed)
        if path.name == "custom_model_file.py":
            allowed.update(custom_model_file_allowed)

        imports = _loushang_imports(path)
        assert sorted(imports) == sorted(allowed & set(imports))


def test_provider_matrix_example_targets_curated_provider_models() -> None:
    module = _load_module(
        Path("examples/ai/11_provider_matrix.py"), "examples_ai_provider_matrix"
    )

    examples = {
        (item.provider_id, item.endpoint_id, item.model_id): item.env_vars
        for item in module.PROVIDER_EXAMPLES
    }

    assert examples[("moonshot", "openai-completions", "kimi-k2.6")]
    assert examples[("baidu-qianfan", "openai-completions-cn", "ernie-5.1")]
    assert examples[("stepfun", "openai-completions", "step-3.7-flash")]
    assert examples[("tencent-hunyuan", "openai-responses", "hy3")]
    assert len(examples) == 11
    assert "openrouter" not in {item.provider_id for item in module.PROVIDER_EXAMPLES}
    assert "amazon-bedrock" not in {
        item.provider_id for item in module.PROVIDER_EXAMPLES
    }


def test_provider_matrix_example_formats_curated_model_line() -> None:
    module = _load_module(
        Path("examples/ai/11_provider_matrix.py"), "examples_ai_provider_matrix_format"
    )

    moonshot = next(
        item for item in module.PROVIDER_EXAMPLES if item.provider_id == "moonshot"
    )
    line = module._format_model_line(moonshot)

    assert "moonshot:openai-completions:kimi-k2.6" in line
    assert "env=MOONSHOT_API_KEY" in line


def test_provider_matrix_example_formats_all_provider_entries() -> None:
    module = _load_module(
        Path("examples/ai/11_provider_matrix.py"), "examples_ai_provider_matrix_all"
    )

    lines = [module._format_model_line(example) for example in module.PROVIDER_EXAMPLES]

    assert len(lines) == len(module.PROVIDER_EXAMPLES)


def test_custom_model_file_example_reports_custom_model_summary() -> None:
    module = _load_module(
        Path("examples/ai/custom_model_file.py"),
        "examples_ai_custom_model_file",
    )

    summary = module.inspect_custom_model_file()

    assert summary["availableModels"] == ["company:openai-completions:company-chat"]
    assert summary["model"] == "company:openai-completions:company-chat"
    assert summary["displayName"] == "Company Chat"
    assert summary["upstreamId"] == "vendor/company-chat-2026-06"
    assert summary["capabilities"] == {"stream": True, "toolUse": True}


def test_usage_online_example_marks_unknown_cost() -> None:
    module = _load_module(
        Path("examples/ai/advanced/usage_online.py"), "examples_ai_usage_online"
    )

    assert module._cost_payload(None) == {"known": False}
    assert module._cost_payload({"input": 0.1, "total": 0.1}) == {
        "known": True,
        "input": 0.1,
        "total": 0.1,
    }


def test_usage_online_example_prints_unknown_cost(capsys, monkeypatch) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage

    module = _load_module(
        Path("examples/ai/advanced/usage_online.py"), "examples_ai_usage_online_main"
    )

    class FakeModel:
        pricing = None

    async def fake_complete(model, context, options):
        return AssistantMessage(
            role="assistant",
            content=[TextPart(type="text", text="ok")],
            api="openai-completions",
            provider="moonshot",
            endpoint="test-endpoint",
            model="kimi-k2.6",
            response_id="resp_1",
            usage=Usage(
                input=1,
                output=1,
                cache_read=0,
                cache_write=0,
                total_tokens=2,
                cost=None,
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )

    monkeypatch.setattr(sys, "argv", ["usage_online.py", "--api-key", "test-key"])
    monkeypatch.setattr(module, "get_model", lambda *_args: FakeModel())
    monkeypatch.setattr(module, "complete", fake_complete)

    assert asyncio.run(module.main()) == 0

    cost_line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("cost: ")
    )
    assert json.loads(cost_line.removeprefix("cost: ")) == {"known": False}


def test_usage_example_reports_response_observation(capsys) -> None:
    module = _load_module(Path("examples/ai/10_usage.py"), "examples_ai_10_usage")

    summary = module.inspect_usage()

    assert summary == {
        "present": True,
        "input": 120,
        "output": 30,
        "cacheRead": 10,
        "cacheWrite": 0,
        "totalTokens": 160,
        "cost": None,
    }

    module.main()
    assert json.loads(capsys.readouterr().out) == summary


def test_reasoning_example_reports_simple_reasoning_mapping(capsys) -> None:
    module = _load_module(
        Path("examples/ai/06_reasoning.py"), "examples_ai_06_reasoning"
    )

    summary = module.inspect_reasoning()

    assert summary == {
        "reasoning": "medium",
        "budgetTokens": 2048,
        "events": [
            {"type": "thinking_delta", "delta": "reasoning trace"},
            {"type": "text_delta", "delta": "mock hello from offline fixture"},
        ],
        "stopReason": "stop",
    }

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_parallel_tools_example_groups_interleaved_calls(capsys) -> None:
    module = _load_module(
        Path("examples/ai/05_parallel_tools.py"), "examples_ai_05_parallel_tools"
    )

    summary = module.inspect_parallel_tools()

    assert summary == {
        "stopReason": "toolUse",
        "toolCalls": [
            {"id": "call_add", "name": "add", "arguments": {"a": 2}},
            {"id": "call_mul", "name": "multiply", "arguments": {"x": 3}},
        ],
    }

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_structured_output_example_parses_result(capsys) -> None:
    module = _load_module(
        Path("examples/ai/07_structured_output.py"),
        "examples_ai_07_structured_output",
    )

    summary = module.inspect_structured_output()

    assert summary == {
        "mode": "json_schema",
        "responseId": "structured-demo",
        "stopReason": "stop",
        "parsed": {"answer": "Paris", "score": 10},
    }

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_image_input_example_reports_image_counts(capsys) -> None:
    module = _load_module(
        Path("examples/ai/08_image_input.py"),
        "examples_ai_08_image_input",
    )

    summary = module.inspect_image_input()

    assert summary == {
        "userImages": 1,
        "toolResultImages": 1,
        "toolResultText": "chart shows growth",
    }

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_openai_codex_live_example_leaves_credential_import_to_auth_api() -> None:
    module = _load_module(
        Path("examples/auth/openai_codex_live_example.py"),
        "examples_auth_openai_codex_live",
    )

    assert not hasattr(module, "load_auth")
    source = Path("examples/auth/openai_codex_live_example.py").read_text(
        encoding="utf-8"
    )
    assert "read_text" not in source
    assert "access_token" not in source
    assert "OpenAICodexCredentialSource" not in source


def test_openai_codex_import_example_calls_public_responses_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from loushang.ai import AssistantMessage, TextPart

    module = _load_module(
        Path("examples/auth/openai_codex_live_example.py"),
        "examples_auth_openai_codex_live_call",
    )
    captured: dict[str, object] = {}
    model = object()
    request_auth = object()

    class AuthenticatedStatus:
        authenticated = True
        auth_kind = "oauth"
        provider = "openai-codex"
        source = "credential_source"
        source_description = "Use existing Codex CLI login"
        source_recovery_hint = "Run codex login"
        experimental = True
        actions: tuple[str, ...] = ()

    def fake_get_model(provider_id: str, endpoint_id: str, model_id: str):
        captured["model_id"] = (provider_id, endpoint_id, model_id)
        return model

    class FakeEventStream:
        async def result(self):
            return AssistantMessage(
                role="assistant",
                content=[TextPart(type="text", text="ok")],
                api="openai-responses",
                provider="openai",
                endpoint="test-endpoint",
                model="gpt-5.5",
                response_id="resp_1",
                usage=None,
                stop_reason="stop",
                error_message=None,
                timestamp=0.0,
            )

    async def fake_get_auth(selected_model):
        captured["auth_model"] = selected_model
        return request_auth

    async def fake_status(selected_model):
        captured["status_model"] = selected_model
        return AuthenticatedStatus()

    async def fake_stream(selected_model, context, options, *, auth=None):
        captured["model"] = selected_model
        captured["context"] = context
        captured["options"] = options
        captured["auth"] = auth
        return FakeEventStream()

    monkeypatch.setattr(module.ai, "get_model", fake_get_model)
    monkeypatch.setattr(module.ai.auth, "status", fake_status)
    monkeypatch.setattr(module.ai.auth, "get_auth", fake_get_auth)
    monkeypatch.setattr(module.ai, "stream", fake_stream)

    assert asyncio.run(module.run()) == "ok"
    assert captured["model_id"] == (
        "openai",
        "coding-responses",
        "gpt-5.5",
    )
    assert captured["model"] is model
    assert captured["status_model"] is model
    assert captured["auth_model"] is model
    assert captured["auth"] is request_auth
    options = captured["options"]
    assert options.auth is None
    assert options.credential is None
    assert options.credential_file is None
    assert not hasattr(options, "oauth_credentials")
    assert options.max_output_tokens is None
    assert options.reasoning.effort == "low"
    output = capsys.readouterr().out
    assert '"authenticated": true' in output
    assert '"source": "credential_source"' in output
    assert "Resolved authentication: object" in output
    assert "Model response:\nok" in output
    assert "Reply exactly: ok" not in captured["context"]["messages"][0]["content"]


def test_errors_retry_example_reports_redacted_error_payload(capsys) -> None:
    module = _load_module(
        Path("examples/ai/09_errors_retry.py"), "examples_ai_09_errors_retry"
    )

    payload = module.inspect_errors_retry()

    assert payload["error"]["code"] == "authentication"
    assert payload["error"]["retryable"] is False
    assert payload["error"]["details"] == {
        "hint": "Set MOONSHOT_API_KEY.",
        "Authorization": "[redacted]",
        "nested": {"refresh" + "_token": "[redacted]"},
    }
    assert payload["typedError"] == {
        "errorType": "AIRateLimitError",
        "code": "rate_limit",
        "statusCode": 429,
        "requestId": "req_error_demo",
    }
    assert payload["retry"]["attempts"] == 2
    assert payload["retry"]["text"] == "retry recovered"
    assert payload["retry"]["trace"] == [
        {
            "schema": "loushang.ai.trace.v1",
            "type": "runtime:request",
            "source": "runtime",
            "name": "request",
            "data": {
                "callId": "retry-demo-call",
                "api": "anthropic-messages",
                "provider": "retry-demo",
                "endpoint": "anthropic-messages",
                "model": "retry-demo",
                "attempt": 1,
                "maxAttempts": 2,
                "upstreamModel": "retry-demo",
            },
        },
        {
            "schema": "loushang.ai.trace.v1",
            "type": "runtime:retry",
            "source": "runtime",
            "name": "retry",
            "data": {
                "callId": "retry-demo-call",
                "api": "anthropic-messages",
                "provider": "retry-demo",
                "endpoint": "anthropic-messages",
                "model": "retry-demo",
                "attempt": 2,
                "maxAttempts": 2,
                "delayMs": 0,
                "reason": "service_unavailable",
                "statusCode": 503,
                "requestId": "req_retry_demo",
            },
        },
        {
            "schema": "loushang.ai.trace.v1",
            "type": "runtime:request",
            "source": "runtime",
            "name": "request",
            "data": {
                "callId": "retry-demo-call",
                "api": "anthropic-messages",
                "provider": "retry-demo",
                "endpoint": "anthropic-messages",
                "model": "retry-demo",
                "attempt": 2,
                "maxAttempts": 2,
                "upstreamModel": "retry-demo",
            },
        },
    ]

    module.main()
    assert json.loads(capsys.readouterr().out) == payload


def test_advanced_inspect_endpoint_contract_formats_protocol_facts(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    module = _load_module(
        Path("examples/ai/advanced/inspect_endpoint_contract.py"),
        "examples_ai_advanced_inspect_endpoint_contract",
    )
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "moonshot": {
                        "endpoints": {
                            "openai-completions": {
                                "api": "openai-completions",
                                "baseUrl": "https://example.invalid/v1",
                                "adapter": {
                                    "store": False,
                                    "developerRole": False,
                                    "strictSchema": False,
                                    "maxOutputTokensField": "max_completion_tokens",
                                    "reasoningEffort": False,
                                    "reasoningFormat": "moonshot",
                                },
                                "models": {
                                    "kimi-k2.6": {
                                        "adapter": {
                                            "reasoningEffort": True,
                                            "streamingUsage": True,
                                        },
                                        "capabilities": {
                                            "input": ["text"],
                                            "output": ["text"],
                                        },
                                    }
                                },
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_model_registry_from_file(path)
    monkeypatch.setattr(module, "load_builtin_model_registry", lambda: registry)

    contract = module.inspect_endpoint_contract()

    assert contract["provider"] == "moonshot"
    assert contract["endpoint"] == "openai-completions"
    assert contract["api"] == "openai-completions"
    assert contract["adapterScope"] == "endpoint-default"
    assert contract["model"] == "kimi-k2.6"
    assert contract["adapter"]["store"] is False
    assert contract["adapter"]["developerRole"] is False
    assert contract["adapter"]["strictSchema"] is False
    assert contract["adapter"]["maxOutputTokensField"] == "max_completion_tokens"
    assert contract["adapter"]["reasoningEffort"] is False
    assert contract["adapter"]["reasoningFormat"] == "moonshot"
    assert contract["requestAdapterScope"] == "model-effective"
    assert contract["requestAdapter"]["store"] is False
    assert contract["requestAdapter"]["developerRole"] is False
    assert contract["requestAdapter"]["reasoningEffort"] is True
    assert contract["requestAdapter"]["maxOutputTokensField"] == "max_completion_tokens"
    assert contract["requestAdapter"]["reasoningFormat"] == "moonshot"
    assert contract["requestBaseUrl"] == "https://example.invalid/v1"
    assert contract["requestHeaderNames"] == ["Authorization"]

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["adapterScope"] == "endpoint-default"
    assert payload["requestAdapterScope"] == "model-effective"


def test_advanced_inspect_endpoint_contract_runs_against_builtin_catalog() -> None:
    module = _load_module(
        Path("examples/ai/advanced/inspect_endpoint_contract.py"),
        "examples_ai_advanced_inspect_endpoint_contract_builtin",
    )

    contract = module.inspect_endpoint_contract()

    assert contract["provider"] == "moonshot"
    assert contract["endpoint"] == "openai-completions"
    assert contract["model"] == "kimi-k2.6"
    assert contract["adapter"]["store"] is False
    assert contract["adapter"]["developerRole"] is False
    assert contract["adapter"]["streamingUsage"] is True
    assert contract["adapter"]["reasoningEffort"] is False
    assert contract["adapter"]["maxOutputTokensField"] == "max_tokens"
    assert contract["adapter"]["reasoningFormat"] == "moonshot"
    assert contract["requestAdapter"]["reasoningEffort"] is False
    assert contract["requestBaseUrl"] == "https://api.moonshot.cn/v1"


def test_advanced_inspect_endpoint_contract_handles_templated_base_url(
    monkeypatch,
    tmp_path,
) -> None:
    module = _load_module(
        Path("examples/ai/advanced/inspect_endpoint_contract.py"),
        "examples_ai_advanced_inspect_endpoint_contract_template",
    )
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "custom-template": {
                        "endpoints": {
                            "openai-completions": {
                                "api": "openai-completions",
                                "baseUrl": "https://example.invalid/{ACCOUNT_ID}/v1",
                                "adapter": {
                                    "maxOutputTokensField": "max_completion_tokens",
                                    "reasoningFormat": "openai",
                                },
                                "models": {
                                    "template-model": {
                                        "capabilities": {
                                            "input": ["text"],
                                            "output": ["text"],
                                        }
                                    }
                                },
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_model_registry_from_file(path)
    monkeypatch.setattr(module, "load_builtin_model_registry", lambda: registry)

    contract = module.inspect_endpoint_contract(
        "custom-template",
        "openai-completions",
        "template-model",
    )

    assert contract["provider"] == "custom-template"
    assert contract["endpoint"] == "openai-completions"
    assert contract["model"] == "template-model"
    assert contract["requestAdapterScope"] == "model-effective"
    assert contract["requestAdapter"]["maxOutputTokensField"] == (
        "max_completion_tokens"
    )
    assert contract["requestAdapter"]["reasoningFormat"] == "openai"


def test_advanced_custom_catalog_uses_typed_upstream_binding() -> None:
    module = _load_module(
        Path("examples/ai/advanced/custom_catalog.py"),
        "examples_ai_advanced_custom_catalog",
    )

    summary = module.inspect_custom_catalog()

    assert summary == {
        "model": "custom-provider:openai-completions:public-model",
        "upstreamId": "vendor/public-model:latest",
        "requestModelUpstreamId": "vendor/public-model:latest",
        "baseUrl": "https://api.example.invalid/v1",
    }


def test_advanced_normalization_diagnostics_reports_stable_payload(capsys) -> None:
    module = _load_module(
        Path("examples/ai/advanced/normalization_diagnostics.py"),
        "examples_ai_advanced_normalization_diagnostics",
    )

    summary = module.inspect_normalization_diagnostics()

    assert summary["messageRoles"] == ["assistant", "toolResult"]
    assert summary["normalizedMessages"] == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "private reasoning"},
                {"type": "text", "text": "answer"},
                {
                    "type": "toolCall",
                    "id": "call_1",
                    "name": "calc",
                    "arguments": {"x": 1},
                    "thoughtSignature": None,
                },
            ],
        },
        {
            "role": "toolResult",
            "toolCallId": "call_1",
            "toolName": "calc",
            "isError": True,
            "details": {"synthetic": True, "reason": "missing_tool_result"},
            "content": [{"type": "text", "text": "No result provided"}],
        },
    ]
    assert summary["diagnostics"] == [
        {
            "code": "thinking_signature_removed",
            "path": "messages[0].content[0]",
            "level": "warning",
        },
        {
            "code": "thinking_downgraded_to_text",
            "path": "messages[0].content[0]",
            "level": "warning",
        },
        {
            "code": "text_signature_removed",
            "path": "messages[0].content[1]",
            "level": "warning",
        },
        {
            "code": "tool_call_id_normalized",
            "path": "messages[0].content[2]",
            "level": "warning",
        },
        {
            "code": "tool_call_thought_signature_removed",
            "path": "messages[0].content[2]",
            "level": "warning",
        },
        {
            "code": "missing_tool_result_repaired",
            "path": "messages[0].content[2]",
            "level": "warning",
        },
    ]

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_advanced_capability_failure_reports_public_error(capsys) -> None:
    module = _load_module(
        Path("examples/ai/advanced/capability_failure.py"),
        "examples_ai_advanced_capability_failure",
    )

    summary = asyncio.run(module.inspect_capability_failure())

    assert summary == {
        "errorType": "UnsupportedCapabilityError",
        "message": "Model 'capability-demo' does not support tool use",
    }

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_advanced_cancel_stream_reports_abort_and_source_close() -> None:
    module = _load_module(
        Path("examples/ai/advanced/cancel_stream.py"),
        "examples_ai_advanced_cancel_stream",
    )

    summary = asyncio.run(module.inspect_stream_cancellation())

    assert summary == {
        "events": ["start", "error"],
        "reason": "aborted",
        "stopReason": "aborted",
        "sourceClosed": True,
    }


def test_advanced_trace_events_reports_schema_and_redaction(capsys) -> None:
    module = _load_module(
        Path("examples/ai/advanced/trace_events.py"),
        "examples_ai_advanced_trace_events",
    )

    summary = asyncio.run(module.inspect_trace_events())

    assert summary == {
        "schemas": ["loushang.ai.trace.v1"],
        "eventTypes": [
            "runtime:request",
            "sdk:client",
            "runtime:retry",
            "runtime:request",
            "sdk:client",
        ],
        "callIdStable": True,
        "text": "trace recovered",
        "privacy": {
            "dataKeys": [],
            "sensitiveValuesAbsent": True,
        },
        "retry": {
            "callId": "<callId>",
            "api": "anthropic-messages",
            "provider": "trace-demo",
            "endpoint": "anthropic-messages",
            "model": "trace-demo",
            "attempt": 2,
            "maxAttempts": 2,
            "delayMs": 0,
            "reason": "service_unavailable",
            "statusCode": 503,
            "requestId": "req_trace_retry",
        },
    }
    assert "secret-token" not in json.dumps(summary, sort_keys=True)

    module.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == summary


def test_advanced_inspect_endpoint_contract_rejects_missing_model(
    monkeypatch,
    tmp_path,
) -> None:
    module = _load_module(
        Path("examples/ai/advanced/inspect_endpoint_contract.py"),
        "examples_ai_advanced_inspect_endpoint_contract_missing_model",
    )
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "moonshot": {
                        "endpoints": {
                            "openai-completions": {
                                "api": "openai-completions",
                                "baseUrl": "https://example.invalid/v1",
                                "adapter": {"developerRole": False},
                                "models": {},
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_model_registry_from_file(path)
    monkeypatch.setattr(module, "load_builtin_model_registry", lambda: registry)

    try:
        module.inspect_endpoint_contract(model_id="missing")
    except KeyError as error:
        assert error.args == (("moonshot", "openai-completions", "missing"),)
    else:
        raise AssertionError("missing model should raise KeyError")


def test_complete_example_builds_expected_context() -> None:
    module = _load_module(Path("examples/ai/01_complete.py"), "examples_ai_complete")

    context = module._build_context()
    summary = module.inspect_complete()

    assert context["system_prompt"]
    assert context["messages"][0]["role"] == "user"
    assert summary == {
        "model": "moonshot:openai-completions:kimi-k2.6",
        "maxOutputTokens": 256,
        "messageCount": 1,
        "responseId": "offline-complete-demo",
        "stopReason": "stop",
        "text": "mock hello from offline fixture",
    }


def test_stream_example_reports_text_delta() -> None:
    module = _load_module(Path("examples/ai/02_stream.py"), "examples_ai_stream")

    summary = module.inspect_stream()

    assert summary["model"] == "moonshot:openai-completions:kimi-k2.6"
    assert summary["responseId"] == "offline-stream-demo"
    assert summary["stopReason"] == "stop"
    assert summary["text"] == "mock hello from offline fixture"
    assert {"type": "text_delta", "delta": "mock hello "} in summary["events"]


def test_tools_example_declares_add_tool() -> None:
    module = _load_module(Path("examples/ai/04_tools.py"), "examples_ai_tools")

    tools = module._build_tools()
    summary = module.inspect_tools()

    assert tools[0]["name"] == "add"
    assert tools[0]["parameters"]["required"] == ["a", "b"]
    assert summary["toolCall"] == {
        "id": "call_add",
        "name": "add",
        "arguments": {"a": 78, "b": 35},
    }
    assert summary["toolResult"] == "113"
    assert "答案是 113" in summary["finalText"]
    assert summary["validation"] == {
        "strict": {"a": 2, "b": 3},
        "strictError": 'Validation failed for tool "add":',
        "coerce": {"a": 2.0, "b": 3.0},
        "diagnostics": [
            {
                "code": "tool_argument_coerced",
                "path": "$.a",
                "fromType": "string",
                "toType": "number",
            },
            {
                "code": "tool_argument_coerced",
                "path": "$.b",
                "fromType": "string",
                "toType": "number",
            },
        ],
    }


def test_typed_context_example_uses_public_types() -> None:
    module = _load_module(
        Path("examples/ai/03_typed_context.py"), "examples_ai_03_typed_context"
    )

    context = module._build_context()
    summary = module.inspect_typed_context()

    assert context.system_prompt is not None
    assert context.messages[0].role == "user"
    assert context.tools is not None
    assert context.tools[0].name == "add"
    assert summary == {
        "model": "moonshot:openai-completions:kimi-k2.6",
        "messageCount": 1,
        "toolCount": 1,
        "stopReason": "stop",
        "text": "mock hello from typed context",
    }


def test_usage_online_example_defaults_to_moonshot_public_route(monkeypatch) -> None:
    module = _load_module(
        Path("examples/ai/advanced/usage_online.py"), "examples_ai_usage_online"
    )

    monkeypatch.setattr(sys, "argv", ["usage_online.py"])

    assert module.parse_args().route == "moonshot-openai"


def test_usage_online_curated_routes_use_provider_credentials() -> None:
    module = _load_module(
        Path("examples/ai/advanced/usage_online.py"), "examples_ai_usage_online_routes"
    )

    assert module.ROUTES["moonshot-openai"].api_key_envs == ("MOONSHOT_API_KEY",)
    assert module.ROUTES["dashscope-responses"].api_key_envs == ("DASHSCOPE_API_KEY",)
    assert module.ROUTES["deepseek-completions"].api_key_envs == ("DEEPSEEK_API_KEY",)


def test_usage_online_routes_exist_in_model_catalog() -> None:
    module = _load_module(
        Path("examples/ai/advanced/usage_online.py"), "examples_ai_usage_online_catalog"
    )

    for route in module.ROUTES.values():
        module.get_model(route.provider, route.endpoint, route.model)
