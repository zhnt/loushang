"""Standard Agent runtime-event projection owned by Channel delivery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from loushang.channel.types import ChannelEnvelope
from loushang.harness.events import (
    RuntimeEvent,
    normalize_event_select,
)
from loushang.harness.session import (
    SUPPORTED_JSON_EVENT_VIEWS,
    JsonEventView,
    project_runtime_event_to_json_views,
    should_emit_runtime_event_view,
)


@dataclass(frozen=True, slots=True)
class AgentRuntimeChannelProjection:
    """Project standard Agent runtime views into Channel envelopes."""

    event_view: JsonEventView = "full"
    event_select: Sequence[str] | str | None = None

    def __post_init__(self) -> None:
        if self.event_view not in SUPPORTED_JSON_EVENT_VIEWS:
            raise ValueError(f"unsupported json event view: {self.event_view}")

    def __call__(
        self,
        event: object,
        operation_id: str | None,
    ) -> tuple[ChannelEnvelope, ...]:
        if not isinstance(event, RuntimeEvent):
            return ()
        selected = normalize_event_select(self.event_select)
        envelopes: list[ChannelEnvelope] = []
        for index, view in enumerate(
            project_runtime_event_to_json_views(
                event,
                event_view=self.event_view,
            ),
            start=1,
        ):
            if not should_emit_runtime_event_view(view, selected):
                continue
            if operation_id is not None:
                view = replace(view, correlation_id=operation_id)
            envelopes.append(
                ChannelEnvelope(
                    envelope_id=f"channel:{event.event_id}:{index}",
                    kind="event",
                    payload=view,
                )
            )
        return tuple(envelopes)


__all__ = ["AgentRuntimeChannelProjection"]
