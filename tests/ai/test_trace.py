from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.trace import TRACE_SCHEMA, emit_trace
from loushang.foundation.observability import log_context
from loushang.foundation.observability._router import (
    configure_observability,
    reset_observability,
)
from loushang.foundation.observability.trace_sink import TraceJSONLSink


def setup_function() -> None:
    reset_observability()


def teardown_function() -> None:
    reset_observability()


def test_emit_trace_emits_versioned_options_callback_event() -> None:
    events: list[dict[str, object]] = []
    event = {"type": "sdk:payload", "model": "kimi-for-coding"}

    emit_trace(SimpleNamespace(trace=events.append), event)

    assert events == [
        {
            "schema": TRACE_SCHEMA,
            "type": "sdk:payload",
            "source": "sdk",
            "name": "payload",
            "data": {"model": "kimi-for-coding"},
        }
    ]


def test_emit_trace_drops_sensitive_options_callback_fields() -> None:
    events: list[dict[str, object]] = []

    emit_trace(
        SimpleNamespace(trace=events.append),
        {
            "type": "sdk:client",
            "headers": {
                "Authorization": "Bearer secret-token",
                "Proxy-Authorization": "Bearer proxy-secret",
                "X-Auth-Token": "auth-secret",
                "X-Amz-Security-Token": "aws-secret",
                "x-api-key": "secret-key",
                "chatgpt-account-id": "account-secret",
                "X-Custom-Signature": "custom-secret",
                "anthropic-version": "2023-06-01",
            },
            "apiKey": "secret-key",
            "openai_api_key": "secret-key",
            "anthropic_api_key": "secret-key",
            "access_token": "secret-token",
            "provider_token": "secret-token",
            "session_cookie": "cookie-secret",
            "token": "secret-token",
            "oauth": {"accessToken": "secret-token"},
            "credentials": {"apiKey": "secret-key", "cookie_header": "cookie-secret"},
            "account_id": "account-secret",
            "nested": {"cookies": "cookie-secret", "total_tokens": 3},
            "prompt": "private prompt",
            "response": "private response",
            "total_tokens": 42,
            "output_tokens": 7,
        },
    )

    payload = json.dumps(events[0], sort_keys=True)
    assert "secret" not in payload
    assert events[0]["data"] == {"total_tokens": 42, "output_tokens": 7}
    assert "private prompt" not in payload
    assert "private response" not in payload


def test_emit_trace_writes_provider_debug_event_to_observability_trace(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "provider.jsonl"
    configure_observability(
        trace_sink=TraceJSONLSink(trace_path),
        trace_scopes={"provider"},
    )

    with log_context(session_id="s1", run_id=6, cwd="/repo", mode="tui"):
        emit_trace(
            None,
            {
                "type": "sdk:tool_done",
                "id": "tool_1",
                "name": "write",
                "args": {"path": "tmp/bmi.html"},
            },
        )

    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["kind"] == "debug_event"
    assert record["scope"] == "provider"
    assert record["name"] == "sdk.tool_done"
    assert record["session_id"] == "s1"
    assert record["run_id"] == 6
    assert record["data"] == {
        "event": {
            "schema": TRACE_SCHEMA,
            "type": "sdk:tool_done",
            "source": "sdk",
            "name": "tool_done",
            "data": {
                "id": "tool_1",
                "name": "write",
                "args": {
                    "kind": "object",
                    "keys": ["path"],
                },
            },
        }
    }


def test_emit_trace_summarizes_tool_content_for_observability_trace(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "provider.jsonl"
    configure_observability(
        trace_sink=TraceJSONLSink(trace_path),
        trace_scopes={"provider"},
    )

    emit_trace(
        None,
        {
            "type": "sdk:tool_done",
            "id": "tool_1",
            "name": "write",
            "args": {"path": "tmp/bmi.html", "content": "<html>secret</html>"},
        },
    )

    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["data"]["event"]["data"]["args"] == {
        "kind": "object",
        "keys": ["content", "path"],
        "content_chars": 19,
    }
    assert "tmp/bmi.html" not in repr(record)
    assert "<html>secret</html>" not in repr(record)


def test_emit_trace_drops_sensitive_observability_fields(tmp_path: Path) -> None:
    trace_path = tmp_path / "provider.jsonl"
    configure_observability(
        trace_sink=TraceJSONLSink(trace_path),
        trace_scopes={"provider"},
    )

    emit_trace(
        None,
        {
            "type": "sdk:client",
            "headers": {
                "Authorization": "Bearer secret-token",
                "Proxy-Authorization": "Bearer proxy-secret",
                "X-Auth-Token": "auth-secret",
                "x-api-key": "secret-key",
                "X-Custom-Signature": "custom-secret",
                "anthropic-version": "2023-06-01",
            },
            "apiKey": "secret-key",
            "total_tokens": 42,
        },
    )

    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    event = record["data"]["event"]["data"]
    assert event == {"total_tokens": 42}


def test_emit_trace_drops_non_json_safe_unknown_values(tmp_path: Path) -> None:
    trace_path = tmp_path / "provider.jsonl"
    configure_observability(
        trace_sink=TraceJSONLSink(trace_path),
        trace_scopes={"provider"},
    )

    emit_trace(None, {"type": "sdk:payload", "path": Path("tmp/bmi.html")})

    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["data"]["event"]["data"] == {}


def test_emit_trace_never_stringifies_exception_messages() -> None:
    events: list[dict[str, object]] = []

    emit_trace(
        SimpleNamespace(trace=events.append),
        {
            "type": "sdk:error",
            "error": RuntimeError("Authorization: Bearer secret-token"),
        },
    )

    assert events[0]["data"]["error"] == {"exceptionType": "RuntimeError"}
    assert "secret-token" not in repr(events)


def test_emit_trace_drops_non_finite_floats(tmp_path: Path) -> None:
    trace_path = tmp_path / "provider.jsonl"
    configure_observability(
        trace_sink=TraceJSONLSink(trace_path),
        trace_scopes={"provider"},
    )

    emit_trace(
        None,
        {"type": "sdk:usage", "nan_value": float("nan"), "inf_value": float("inf")},
    )

    raw_text = trace_path.read_text(encoding="utf-8")
    record = json.loads(raw_text)
    assert "NaN" not in raw_text
    assert "Infinity" not in raw_text
    assert record["data"]["event"]["data"] == {}
