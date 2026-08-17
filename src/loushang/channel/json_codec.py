from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, cast

from loushang.channel.types import ChannelEndpoint, ChannelEnvelope
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.events.projection import RuntimeEventView
from loushang.harnesswork.types import WorkEvent, WorkOperation


def channel_envelope_to_json(envelope: ChannelEnvelope) -> dict[str, JSONValue]:
    data = {
        "envelope_id": _require_string(envelope.envelope_id, "envelope_id"),
        "kind": _require_envelope_kind(envelope.kind),
        "payload": _payload_to_json(envelope.payload),
        "source": _endpoint_to_json(envelope.source),
        "target": _endpoint_to_json(envelope.target),
        "created_at": _datetime_to_json(envelope.created_at, "created_at"),
        "metadata": _to_json_mapping(envelope.metadata),
    }
    return require_json_mapping(data, name="channel_envelope")


def channel_envelope_from_json(data: Mapping[str, object]) -> ChannelEnvelope:
    data = require_json_mapping(dict(data), name="channel_envelope")
    kind = _require_envelope_kind(data["kind"])
    payload_data = _require_mapping(data["payload"], "payload")
    return ChannelEnvelope(
        envelope_id=_require_string(data["envelope_id"], "envelope_id"),
        kind=kind,
        payload=_payload_from_json(kind, payload_data),
        source=_endpoint_from_json(data.get("source"), "source"),
        target=_endpoint_from_json(data.get("target"), "target"),
        created_at=_datetime_from_json(data.get("created_at")),
        metadata=_mapping_or_empty(data.get("metadata")),
    )


def _payload_to_json(
    payload: WorkOperation | WorkEvent | RuntimeEventView,
) -> dict[str, object]:
    if isinstance(payload, WorkOperation):
        return {
            "operation_id": _require_string(payload.operation_id, "operation_id"),
            "kind": _require_string(payload.kind, "payload.kind"),
            "session_id": _require_optional_string(
                payload.session_id, "payload.session_id"
            ),
            "domain": _require_string(payload.domain, "payload.domain"),
            "payload": _to_json_mapping(payload.payload),
            "source": _to_json_mapping(payload.source),
        }
    if isinstance(payload, WorkEvent):
        return {
            "event_id": _require_string(payload.event_id, "event_id"),
            "kind": _require_string(payload.kind, "payload.kind"),
            "run_id": _require_string(payload.run_id, "run_id"),
            "session_id": _require_string(payload.session_id, "payload.session_id"),
            "domain": _require_string(payload.domain, "payload.domain"),
            "operation_id": _require_string(payload.operation_id, "operation_id"),
            "sequence": _require_integer(payload.sequence, "sequence"),
            "created_at": _required_datetime_to_json(
                payload.created_at, "payload.created_at"
            ),
            "delivery_hint": _require_delivery_hint(payload.delivery_hint),
            "payload": _to_json_mapping(payload.payload),
            "source_event_ref": _require_optional_string(
                payload.source_event_ref, "source_event_ref"
            ),
        }
    return {
        "event_family": "runtime",
        "event_id": _require_string(payload.event_id, "event_id"),
        "kind": _require_string(payload.kind, "payload.kind"),
        "stream_id": _require_string(payload.stream_id, "stream_id"),
        "sequence": _require_integer(payload.sequence, "sequence"),
        "occurred_at": _required_datetime_to_json(
            payload.occurred_at, "payload.occurred_at"
        ),
        "event_type": _require_string(payload.event_type, "event_type"),
        "view": _require_string(payload.view, "view"),
        "delivery_hint": _require_delivery_hint(payload.delivery_hint),
        "payload": _to_json_mapping(payload.payload),
        "session_id": _require_optional_string(payload.session_id, "session_id"),
        "run_id": _require_optional_string(payload.run_id, "run_id"),
        "source_event_ref": _require_optional_string(
            payload.source_event_ref, "source_event_ref"
        ),
        "source_record_id": _require_optional_string(
            payload.source_record_id, "source_record_id"
        ),
        "correlation_id": _require_optional_string(
            payload.correlation_id, "correlation_id"
        ),
    }


def _payload_from_json(
    kind: Literal["operation", "event"], data: Mapping[str, object]
) -> WorkOperation | WorkEvent | RuntimeEventView:
    if kind == "operation":
        return WorkOperation(
            operation_id=_require_string(data["operation_id"], "operation_id"),
            kind=_require_string(data["kind"], "payload.kind"),
            session_id=_require_optional_string(
                data["session_id"], "payload.session_id"
            ),
            domain=_require_string(data["domain"], "payload.domain"),
            payload=_mapping_or_empty(data.get("payload")),
            source=_mapping_or_empty(data.get("source")),
        )
    if data.get("event_family") == "runtime":
        return RuntimeEventView(
            event_id=_require_string(data["event_id"], "event_id"),
            kind=_require_string(data["kind"], "payload.kind"),
            stream_id=_require_string(data["stream_id"], "stream_id"),
            sequence=_require_integer(data["sequence"], "sequence"),
            occurred_at=_required_datetime_from_json(
                data["occurred_at"], "occurred_at"
            ),
            event_type=_require_string(data["event_type"], "event_type"),
            view=_require_string(data["view"], "view"),
            delivery_hint=_require_delivery_hint(data["delivery_hint"]),
            payload=_mapping_or_empty(data.get("payload")),
            session_id=_require_optional_string(data.get("session_id"), "session_id"),
            run_id=_require_optional_string(data.get("run_id"), "run_id"),
            source_event_ref=_require_optional_string(
                data.get("source_event_ref"), "source_event_ref"
            ),
            source_record_id=_require_optional_string(
                data.get("source_record_id"), "source_record_id"
            ),
            correlation_id=_require_optional_string(
                data.get("correlation_id"), "correlation_id"
            ),
        )
    return WorkEvent(
        event_id=_require_string(data["event_id"], "event_id"),
        kind=_require_string(data["kind"], "payload.kind"),
        run_id=_require_string(data["run_id"], "run_id"),
        session_id=_require_string(data["session_id"], "payload.session_id"),
        domain=_require_string(data["domain"], "payload.domain"),
        operation_id=_require_string(data["operation_id"], "operation_id"),
        sequence=_require_integer(data["sequence"], "sequence"),
        created_at=_required_datetime_from_json(data["created_at"]),
        delivery_hint=_require_delivery_hint(data["delivery_hint"]),
        payload=_mapping_or_empty(data.get("payload")),
        source_event_ref=_require_optional_string(
            data.get("source_event_ref"), "source_event_ref"
        ),
    )


def _endpoint_to_json(endpoint: ChannelEndpoint | None) -> dict[str, object] | None:
    if endpoint is None:
        return None
    return {
        "endpoint_id": _require_string(endpoint.endpoint_id, "endpoint_id"),
        "kind": _require_string(endpoint.kind, "endpoint.kind"),
        "session_id": _require_optional_string(
            endpoint.session_id, "endpoint.session_id"
        ),
        "metadata": _to_json_mapping(endpoint.metadata),
    }


def _endpoint_from_json(value: object, field_name: str) -> ChannelEndpoint | None:
    if value is None:
        return None
    data = _require_mapping(value, field_name)
    return ChannelEndpoint(
        endpoint_id=_require_string(data["endpoint_id"], f"{field_name}.endpoint_id"),
        kind=_require_string(data["kind"], f"{field_name}.kind"),
        session_id=_require_optional_string(
            data.get("session_id"), f"{field_name}.session_id"
        ),
        metadata=_mapping_or_empty(data.get("metadata")),
    )


def _datetime_from_json(value: object) -> datetime | None:
    if value is None:
        return None
    return _required_datetime_from_json(value)


def _required_datetime_from_json(
    value: object, field_name: str = "created_at"
) -> datetime:
    value = _require_string(value, field_name)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime") from exc


def _datetime_to_json(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_datetime_to_json(value, field_name)


def _required_datetime_to_json(value: object, field_name: str) -> str:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    return cast(datetime, value).isoformat()


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    return require_json_mapping(
        dict(_require_mapping(value, "mapping")),
        name="channel_mapping",
    )


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{field_name} must be a JSON object")
    return cast(dict[str, object], value)


def _require_string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    return cast(str, value)


def _require_optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    return cast(int, value)


def _require_literal(
    value: object,
    field_name: str,
    allowed: tuple[str, ...],
) -> str:
    value = _require_string(value, field_name)
    if value not in allowed:
        choices = " or ".join(repr(item) for item in allowed)
        raise ValueError(f"{field_name} must be {choices}")
    return value


def _require_envelope_kind(value: object) -> Literal["operation", "event"]:
    return cast(
        Literal["operation", "event"],
        _require_literal(value, "kind", ("operation", "event")),
    )


def _require_delivery_hint(
    value: object,
) -> Literal["immediate", "coalesce", "final_only"]:
    return cast(
        Literal["immediate", "coalesce", "final_only"],
        _require_literal(
            value,
            "delivery_hint",
            ("immediate", "coalesce", "final_only"),
        ),
    )


def _to_json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object], require_json_mapping(dict(value), name="channel_mapping")
    )


__all__ = [
    "channel_envelope_from_json",
    "channel_envelope_to_json",
]
