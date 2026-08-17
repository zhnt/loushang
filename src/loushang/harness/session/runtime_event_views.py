"""Shared JSON views from common runtime facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from loushang.harness.events.json import snake_case_json_keys
from loushang.harness.events.projection import (
    RuntimeEventDeliveryHint,
    RuntimeEventView,
    matches_event_select,
    project_runtime_event,
)
from loushang.harness.events.runtime_projection import project_session_runtime_event
from loushang.harness.events.types import RuntimeEvent
from loushang.harness.presentation import ToolDefinitionResolver, ToolRenderRuntime
from loushang.harness.session.event_projection import (
    JsonEventView,
    _event_correlation_id,
    _expand_patterns,
    project_session_event,
)


def project_runtime_event_to_json_views(
    event: RuntimeEvent[object],
    *,
    event_view: JsonEventView,
    tool_render_runtime: ToolRenderRuntime | None = None,
    tool_definition_resolver: ToolDefinitionResolver | None = None,
    tool_render_expanded: bool = False,
) -> tuple[RuntimeEventView, ...]:
    """Project one common runtime fact into Coding's selected JSON view.

    Coding supplies product view selection and tool-render policy. The
    transport payload uses the shared snake_case event contract owned by
    Harness; no Pi or camelCase aliases are expanded here.
    """

    session_event = project_session_runtime_event(event)
    if session_event is None:
        return ()
    views: list[RuntimeEventView] = []
    for payload in project_session_event(
        session_event,
        event_view=event_view,
        tool_render_runtime=tool_render_runtime,
        tool_definition_resolver=tool_definition_resolver,
        tool_render_expanded=tool_render_expanded,
    ):
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            continue
        views.append(
            project_runtime_event(
                event,
                event_type=event_type,
                view=event_view,
                payload=payload,
                delivery_hint=_delivery_hint(event_type),
                correlation_id=_event_correlation_id(payload),
            )
        )
    return tuple(views)


def should_emit_runtime_event_view(
    view: RuntimeEventView,
    event_select: Sequence[str],
) -> bool:
    """Apply the shared exact/prefix selector contract to a runtime view."""

    return matches_event_select(view.event_type, _expand_patterns(event_select))


def shape_runtime_event_view(view: RuntimeEventView) -> dict[str, Any]:
    """Shape one projected view using the shared snake_case stream contract."""

    payload = snake_case_json_keys(view.payload)
    if not isinstance(payload, dict):
        raise TypeError("runtime event view payload must be a JSON object")
    payload.setdefault("type", view.event_type)
    payload.setdefault("event_type", view.event_type)
    stream: dict[str, Any] = {
        "kind": "session_event",
        "view": view.view,
    }
    if view.correlation_id is not None:
        payload["correlation_id"] = view.correlation_id
        stream["correlation_id"] = view.correlation_id
    payload["stream"] = stream
    return payload


def _delivery_hint(event_type: str) -> RuntimeEventDeliveryHint:
    if event_type in {"assistant_delta", "tool_execution_update"}:
        return "coalesce"
    return "immediate"


__all__ = [
    "project_runtime_event_to_json_views",
    "shape_runtime_event_view",
    "should_emit_runtime_event_view",
]
