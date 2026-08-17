from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias, cast

from loushang.agent.types import AgentToolResult
from loushang.ai.json_codec import serialize_assistant_message_event
from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.events.json import snake_case_json_keys
from loushang.harness.events.projection import matches_event_select
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.session.event_serialization import serialize_session_event
from loushang.harness.tools.core import ToolRenderOutput
from loushang.harness.transcript import create_agent_transcript_message_codec

SessionEvent: TypeAlias = Mapping[str, Any]
JsonEventView = Literal["full", "compact", "assistant_stream", "tools", "final"]

SUPPORTED_JSON_EVENT_VIEWS: tuple[JsonEventView, ...] = (
    "full",
    "compact",
    "assistant_stream",
    "tools",
    "final",
)
_MESSAGE_CODEC = create_agent_transcript_message_codec()
serialize_agent_message = _MESSAGE_CODEC.serialize

def select_events(*patterns: str) -> tuple[str, ...]:
    return patterns


def project_session_event(
    event: SessionEvent,
    *,
    event_view: JsonEventView,
    tool_render_runtime: ToolRenderRuntime | None = None,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    tool_render_expanded: bool = False,
) -> list[dict[str, Any]]:
    if event_view == "full":
        payloads = [serialize_session_event(event)]
        return _with_rendered_tool_payloads(
            payloads,
            event,
            tool_render_runtime=tool_render_runtime,
            tool_definition_resolver=tool_definition_resolver,
            tool_render_expanded=tool_render_expanded,
        )
    if event_view == "compact":
        payloads = _project_compact_event(event)
        return _with_rendered_tool_payloads(
            payloads,
            event,
            tool_render_runtime=tool_render_runtime,
            tool_definition_resolver=tool_definition_resolver,
            tool_render_expanded=tool_render_expanded,
        )
    if event_view == "assistant_stream":
        return _project_assistant_stream_event(event)
    if event_view == "tools":
        payloads = _project_tools_event(event)
        return _with_rendered_tool_payloads(
            payloads,
            event,
            tool_render_runtime=tool_render_runtime,
            tool_definition_resolver=tool_definition_resolver,
            tool_render_expanded=tool_render_expanded,
        )
    if event_view == "final":
        return _project_final_event(event)
    raise ValueError(f"unsupported json event view: {event_view}")


def should_emit_projected_event(
    payload: dict[str, Any], event_select: Sequence[str]
) -> bool:
    if not event_select:
        return True
    event_type = payload.get("type")
    if not isinstance(event_type, str):
        return False
    expanded = _expand_patterns(event_select)
    return matches_event_select(event_type, expanded)


def shape_stream_event(
    payload: dict[str, Any], *, event_view: JsonEventView
) -> dict[str, Any]:
    shaped = snake_case_json_keys(payload)
    if not isinstance(shaped, dict):
        raise TypeError("event payload must project to a JSON object")
    event_type = shaped.get("type")
    if isinstance(event_type, str):
        shaped.setdefault("event_type", event_type)
    correlation_id = _event_correlation_id(shaped)
    stream: dict[str, Any] = {
        "kind": "session_event",
        "view": event_view,
    }
    if correlation_id is not None:
        shaped["correlation_id"] = correlation_id
        stream["correlation_id"] = correlation_id
    shaped["stream"] = stream
    return shaped


def _expand_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    return tuple(patterns)


def _project_compact_event(event: SessionEvent) -> list[dict[str, Any]]:
    event_type = event["type"]
    if event_type in {"tool_execution_start", "tool_execution_end"}:
        return [serialize_session_event(event)]
    if event_type == "message_update":
        assistant_delta = _serialize_assistant_delta(event)
        return [assistant_delta] if assistant_delta is not None else []
    if event_type == "message_end":
        assistant_final = _serialize_assistant_final(event)
        return [assistant_final] if assistant_final is not None else []
    return []


def _project_assistant_stream_event(event: SessionEvent) -> list[dict[str, Any]]:
    event_type = event["type"]
    if event_type == "message_update":
        assistant_delta = _serialize_assistant_delta(event)
        return [assistant_delta] if assistant_delta is not None else []
    if event_type == "message_end":
        assistant_final = _serialize_assistant_final(event)
        return [assistant_final] if assistant_final is not None else []
    return []


def _project_tools_event(event: SessionEvent) -> list[dict[str, Any]]:
    if event["type"] in {
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    }:
        return [serialize_session_event(event)]
    return []


def _with_rendered_tool_payloads(
    payloads: list[dict[str, Any]],
    event: SessionEvent,
    *,
    tool_render_runtime: ToolRenderRuntime | None,
    tool_definition_resolver: ToolDefinitionResolver | None,
    tool_render_expanded: bool,
) -> list[dict[str, Any]]:
    if not payloads or tool_render_runtime is None or tool_definition_resolver is None:
        return payloads
    event_type = event["type"]
    if event_type not in {
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    }:
        return payloads
    if event_type == "tool_execution_end":
        collapsed = _serialize_tool_render_output(
            _render_tool_event(
                event,
                tool_render_runtime=tool_render_runtime,
                tool_definition_resolver=tool_definition_resolver,
                expanded=False,
            )
        )
        expanded = _serialize_tool_render_output(
            _render_tool_event(
                event,
                tool_render_runtime=tool_render_runtime,
                tool_definition_resolver=tool_definition_resolver,
                expanded=True,
            )
        )
        serialized = expanded if tool_render_expanded else collapsed
        collapsed_text = _payload_plain_text(collapsed)
        expanded_text = _payload_plain_text(expanded)
    else:
        serialized = _serialize_tool_render_output(
            _render_tool_event(
                event,
                tool_render_runtime=tool_render_runtime,
                tool_definition_resolver=tool_definition_resolver,
                expanded=tool_render_expanded,
            )
        )
        collapsed_text = (
            _payload_plain_text(serialized) if not tool_render_expanded else None
        )
        expanded_text = (
            _payload_plain_text(serialized) if tool_render_expanded else None
        )
    if serialized is None:
        return payloads
    output_key = (
        "rendered_tool_call"
        if event_type == "tool_execution_start"
        else "rendered_tool_result"
    )
    enriched: list[dict[str, Any]] = []
    for payload in payloads:
        updated = dict(payload)
        rendered_payload = _with_render_contract(
            serialized,
            event,
            output_key=output_key,
            expanded=tool_render_expanded,
            collapsed_text=collapsed_text,
            expanded_text=expanded_text,
        )
        if output_key == "rendered_tool_result":
            rendered_payload.setdefault("is_partial", event_type == "tool_execution_update")
            rendered_payload.setdefault("expanded", tool_render_expanded)
        updated[output_key] = rendered_payload
        enriched.append(updated)
    return enriched


def _render_tool_event(
    event: SessionEvent,
    *,
    tool_render_runtime: ToolRenderRuntime,
    tool_definition_resolver: ToolDefinitionResolver,
    expanded: bool,
) -> ToolRenderOutput:
    try:
        return cast(
            ToolRenderOutput,
            tool_render_runtime.render_event(
                event,
                tool_definition_resolver,
                expanded=expanded,
            ),
        )
    except Exception:
        return None


def _serialize_tool_render_output(rendered: ToolRenderOutput) -> dict[str, Any] | None:
    if rendered is None:
        return None
    if isinstance(rendered, str):
        return {"type": "text", "text": rendered, "plain_text": rendered}
    if isinstance(rendered, dict):
        try:
            payload = require_json_mapping(rendered, name="rendered_tool_output")
            normalized = snake_case_json_keys(payload)
            if not isinstance(normalized, dict):
                return None
            payload = normalized
        except JsonValueError:
            return None
        if isinstance(payload.get("html"), str):
            payload.setdefault("type", "html")
        elif isinstance(payload.get("text"), str):
            payload.setdefault("type", "text")
        else:
            payload.setdefault("type", "custom")
        text = payload.get("text")
        if isinstance(text, str):
            payload.setdefault("plain_text", text)
        return payload
    return None


def _with_render_contract(
    payload: dict[str, Any],
    event: SessionEvent,
    *,
    output_key: str,
    expanded: bool,
    collapsed_text: str | None,
    expanded_text: str | None,
) -> dict[str, Any]:
    rendered_payload = dict(payload)
    rendered_payload.setdefault("contract_version", 1)
    if output_key == "rendered_tool_call":
        rendered_payload.setdefault("status", "running")
        return rendered_payload

    rendered_payload.setdefault("status", _rendered_tool_result_status(event))
    duration_ms = _rendered_tool_duration_ms(event, rendered_payload)
    if duration_ms is not None:
        rendered_payload.setdefault("duration_ms", duration_ms)
    if collapsed_text is not None:
        rendered_payload.setdefault("collapsed_text", collapsed_text)
    if expanded_text is not None:
        rendered_payload.setdefault("expanded_text", expanded_text)
    rendered_payload.setdefault("artifacts", _rendered_tool_artifacts(event))
    rendered_payload.setdefault("expanded", expanded)
    return rendered_payload


def _payload_plain_text(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    plain_text = payload.get("plain_text")
    if isinstance(plain_text, str):
        return plain_text
    text = payload.get("text")
    return text if isinstance(text, str) else None


def _rendered_tool_result_status(event: SessionEvent) -> str:
    if event["type"] == "tool_execution_update":
        return "partial"
    result = event.get("result")
    details = _event_result_details(result)
    if details:
        if details.get("timed_out") is True:
            return "timed_out"
        if details.get("cancelled") is True:
            return "cancelled"
    if bool(event.get("is_error", False)):
        return "error"
    if isinstance(result, AgentToolResult) and result.terminate:
        return "terminate"
    return "ok"


def _rendered_tool_duration_ms(
    event: SessionEvent, payload: Mapping[str, Any]
) -> int | None:
    for candidate in (payload.get("duration_ms"),):
        resolved = _non_negative_int(candidate)
        if resolved is not None:
            return resolved
    result = (
        event.get("partial_result")
        if event["type"] == "tool_execution_update"
        else event.get("result")
    )
    details = _event_result_details(result)
    if details:
        for key in ("duration_ms", "elapsed_ms"):
            resolved = _non_negative_int(details.get(key))
            if resolved is not None:
                return resolved
    for candidate in (event.get("duration_ms"),):
        resolved = _non_negative_int(candidate)
        if resolved is not None:
            return resolved
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return round(value)
    return None


def _rendered_tool_artifacts(event: SessionEvent) -> list[dict[str, str]]:
    result = (
        event.get("partial_result")
        if event["type"] == "tool_execution_update"
        else event.get("result")
    )
    event_details = _event_result_details(result)
    if not event_details:
        return []
    details = event_details
    artifacts: list[dict[str, str]] = []
    for key in ("stdout_artifact_path", "stderr_artifact_path", "full_output_path"):
        value = details.get(key)
        if (
            isinstance(value, str)
            and value
            and all(artifact["path"] != value for artifact in artifacts)
        ):
            artifact = {
                "type": "file",
                "path": value,
                "name": _artifact_name(value),
            }
            stream = _artifact_stream(key)
            if stream is not None:
                artifact["stream"] = stream
            artifacts.append(artifact)
    return artifacts


def _event_result_details(result: object) -> Mapping[str, Any]:
    if not isinstance(result, AgentToolResult):
        return {}
    try:
        details = result.event_details()
    except Exception:
        return {}
    return details if isinstance(details, Mapping) else {}


def _artifact_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or path


def _artifact_stream(key: str) -> str | None:
    if key.startswith("stdout"):
        return "stdout"
    if key.startswith("stderr"):
        return "stderr"
    return None


def _project_final_event(event: SessionEvent) -> list[dict[str, Any]]:
    if event["type"] != "message_end":
        return []
    assistant_final = _serialize_assistant_final(event)
    return [assistant_final] if assistant_final is not None else []


def _serialize_assistant_delta(event: SessionEvent) -> dict[str, Any] | None:
    if event["type"] != "message_update":
        return None
    message = event["message"]
    if getattr(message, "role", None) != "assistant":
        return None
    assistant_event = snake_case_json_keys(
        serialize_assistant_message_event(event["assistant_message_event"])
    )
    if not isinstance(assistant_event, dict):
        return None
    assistant_event_type = assistant_event["type"]
    if assistant_event_type in {"text_delta", "thinking_delta", "toolcall_delta"}:
        return {
            "type": "assistant_delta",
            "event_type": assistant_event_type,
            "content_index": assistant_event["content_index"],
            "delta": assistant_event["delta"],
        }
    return {
        "type": "assistant_event",
        "assistant_message_event": assistant_event,
    }


def _serialize_assistant_final(event: SessionEvent) -> dict[str, Any] | None:
    if event["type"] != "message_end":
        return None
    message = event["message"]
    if getattr(message, "role", None) != "assistant":
        return None
    return {
        "type": "assistant_final",
        "message": snake_case_json_keys(serialize_agent_message(message)),
    }


def _event_correlation_id(payload: dict[str, Any]) -> str | None:
    for key in ("tool_call_id", "message_id", "entry_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    message = payload.get("message")
    if isinstance(message, dict):
        value = message.get("id")
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "JsonEventView",
    "SUPPORTED_JSON_EVENT_VIEWS",
    "SessionEvent",
    "project_session_event",
    "select_events",
    "shape_stream_event",
    "should_emit_projected_event",
]
