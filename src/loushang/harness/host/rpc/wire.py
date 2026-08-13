"""Pure projection helpers for the existing RPC wire contract."""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, cast

from loushang.ai.model import ModelSelection
from loushang.harness.host.json_projection import project_host_value
from loushang.harness.host.rpc.types import RpcModel, RpcModelCost, RpcSessionState

_MISSING = object()
_THINKING_LEVELS = frozenset({"off", "minimal", "low", "medium", "high", "xhigh"})


def project_session_state(session: Any) -> RpcSessionState:
    state = session.get_state()
    session_id = _safe_getattr(session, "session_id", None)
    if session_id is None:
        session_id_value = ""
    elif isinstance(session_id, str):
        session_id_value = session_id
    else:
        session_id_value = _safe_string(session_id)

    session_name = _safe_getattr(session, "session_name", None)
    if session_name is not None and not isinstance(session_name, str):
        session_name = _safe_string(session_name)

    session_file = _safe_getattr(session, "session_file", None)
    if isinstance(session_file, Path):
        session_file_value: str | None = str(session_file)
    elif session_file is None:
        session_file_value = None
    else:
        session_file_value = _safe_string(session_file)

    steering = _list_attr(state, "steering")
    follow_up = _list_attr(state, "follow_up")
    thinking_level = _safe_getattr(state, "thinking_level", "off")
    if not isinstance(thinking_level, str):
        thinking_level = _safe_string(thinking_level) or "off"
    if thinking_level not in _THINKING_LEVELS:
        thinking_level = "off"
    try:
        model = project_state_model(session, state)
    except Exception:
        model = None

    payload: RpcSessionState = {
        "sessionId": session_id_value,
        "model": model,
        "isStreaming": _run_status(state) == "running",
        "isCompacting": bool(_safe_getattr(state, "is_compacting", False)),
        "steeringMode": _queue_mode(session, "steering_mode"),
        "followUpMode": _queue_mode(session, "follow_up_mode"),
        "autoCompactionEnabled": bool(
            _safe_getattr(session, "auto_compaction_enabled", False)
        ),
        "messageCount": len(session_messages(session)),
        "pendingMessageCount": len(steering) + len(follow_up),
        "thinkingLevel": thinking_level,
    }
    if isinstance(session_name, str) and session_name:
        payload["sessionName"] = session_name
    if session_file_value:
        payload["sessionFile"] = session_file_value
    return payload


def project_state_model(session: Any, state: Any) -> RpcModel | None:
    agent = _safe_getattr(session, "agent", None)
    agent_state = _safe_getattr(agent, "state", None)
    model = _safe_getattr(agent_state, "model", None)
    if model is not None:
        try:
            payload = _project_model(session, model)
            if payload is not None and not _is_unknown_model(payload):
                return payload
        except Exception:
            pass

    selection = _safe_getattr(state, "model_selection", None)
    resolved_model = _resolve_model(session, selection)
    if resolved_model is not None:
        try:
            payload = _project_model(session, resolved_model)
            if payload is not None and not _is_unknown_model(payload):
                return payload
        except Exception:
            pass

    try:
        payload = _project_model_selection_as_model(selection)
        if payload is not None and not _is_unknown_model(payload):
            return payload
        return _project_default_model(session)
    except Exception:
        return None


def project_available_models(session: Any, selections: list[Any]) -> list[RpcModel]:
    serialized: list[RpcModel] = []
    for selection in selections:
        try:
            resolved_model = _resolve_model(session, selection)
            payload = (
                _project_model(session, resolved_model)
                if resolved_model is not None
                else _project_model_selection_as_model(selection)
            )
        except Exception:
            continue
        if payload is not None:
            serialized.append(payload)
    return serialized


def project_session_stats(stats: Any) -> dict[str, Any]:
    return cast(dict[str, Any], camelize(project_json_value(stats)))


def project_session_listing_item(session: Any) -> dict[str, Any]:
    fields = (
        "session_id",
        "cwd",
        "session_file",
        "parent_session",
        "leaf_id",
        "created_at",
        "updated_at",
        "name",
        "message_count",
        "entry_count",
        "first_message",
        "all_messages_text",
        "last_message_preview",
        "model",
        "has_diagnostics",
        "diagnostic_count",
        "last_diagnostic_code",
        "last_diagnostic_level",
    )
    raw = {
        name: value
        for name in fields
        if (value := _safe_getattr(session, name, _MISSING)) is not _MISSING
    }
    if not isinstance(raw.get("session_id"), str):
        raise TypeError("session listing items require session_id")
    serialized = project_json_value(raw)
    if not isinstance(serialized, dict):
        raise TypeError("session listing items must serialize to objects")
    return cast(dict[str, Any], camelize(serialized))


def project_command_descriptor(command: object) -> dict[str, Any]:
    name = _safe_getattr(command, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError("command descriptor requires name")
    description = _safe_getattr(command, "description", None)
    source = _safe_getattr(command, "source", None)
    payload = {
        "name": name,
        "description": description if isinstance(description, str) else None,
        "source": source if isinstance(source, str) else "",
        "sourceInfo": _project_command_source_info(
            _safe_getattr(command, "source_info", None)
        ),
    }
    invocation_name = _safe_getattr(command, "invocation_name", None)
    if isinstance(invocation_name, str) and invocation_name:
        payload["invocationName"] = invocation_name
    conflict_group = _safe_getattr(command, "conflict_group", None)
    if isinstance(conflict_group, str) and conflict_group:
        payload["conflictGroup"] = conflict_group
    argument_hint = _safe_getattr(command, "argument_hint", None)
    if isinstance(argument_hint, str) and argument_hint:
        payload["argumentHint"] = argument_hint
    return payload


def session_messages(session: Any) -> list[object]:
    context_getter = _safe_getattr(session, "get_session_context", None)
    if callable(context_getter):
        try:
            context = context_getter()
        except Exception:
            context = None
        else:
            messages = _safe_getattr(context, "messages", None)
            if isinstance(messages, list | tuple):
                return list(messages)
    messages = _safe_getattr(session, "messages", None)
    if isinstance(messages, list | tuple):
        return list(messages)
    return []


def project_model_selection(
    selection: ModelSelection | None,
) -> dict[str, str] | None:
    if selection is None:
        return None
    return {
        "provider": selection.provider,
        "endpointId": selection.endpoint_id,
        "modelId": selection.model_id,
    }


def project_model_cost(pricing: object) -> RpcModelCost | None:
    if pricing is None:
        return None
    input_cost = _safe_getattr(pricing, "input", None)
    output_cost = _safe_getattr(pricing, "output", None)
    cache_read = _safe_getattr(pricing, "cache_read", None)
    cache_write = _safe_getattr(pricing, "cache_write", None)
    values = (input_cost, output_cost, cache_read, cache_write)
    if any(
        value is None
        or isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or value < 0
        for value in values
    ):
        return None
    return {
        "input": cast(float | int, input_cost),
        "output": cast(float | int, output_cost),
        "cacheRead": cast(float | int, cache_read),
        "cacheWrite": cast(float | int, cache_write),
    }


def project_json_value(value: object) -> object:
    return project_host_value(value, name="rpc_output", surface="RPC")


def camelize(value: object) -> object:
    if isinstance(value, dict):
        return {
            _snake_to_camel(str(key)): camelize(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [camelize(item) for item in value]
    return value


def _run_status(state: Any) -> str:
    run = _safe_getattr(state, "run", None)
    status = _safe_getattr(run, "status", None)
    return status if isinstance(status, str) else "idle"


def _queue_mode(session: Any, attr: str) -> str:
    value = _safe_getattr(session, attr, None)
    if value in {"all", "one-at-a-time"}:
        return value
    agent_value = _safe_getattr(_safe_getattr(session, "agent", None), attr, None)
    if agent_value in {"all", "one-at-a-time"}:
        return agent_value
    return "one-at-a-time"


def _list_attr(target: Any, attr: str) -> list[object]:
    value = _safe_getattr(target, attr, None)
    return list(value) if isinstance(value, list) else []


def _project_default_model(session: Any) -> RpcModel | None:
    getter = getattr(session, "get_available_models", None)
    if not callable(getter):
        return None
    try:
        models = getter()
    except Exception:
        return None
    if not isinstance(models, list):
        return None
    for selection in models:
        try:
            payload = _project_model_selection_as_model(selection)
        except Exception:
            payload = None
        if payload is not None and not _is_unknown_model(payload):
            return payload
        try:
            resolved = _resolve_model(session, selection)
        except Exception:
            resolved = None
        if resolved is None:
            continue
        try:
            payload = _project_model(session, resolved)
        except Exception:
            payload = None
        if payload is not None and not _is_unknown_model(payload):
            return payload
    return None


def _resolve_model(session: Any, selection: Any) -> object | None:
    registry = _safe_getattr(session, "model_registry", None)
    builder = _safe_getattr(registry, "build_model", None)
    if selection is not None and callable(builder):
        try:
            return builder(selection)
        except Exception:
            return None
    return None


def _project_command_source_info(source_info: object) -> dict[str, Any]:
    path = _safe_getattr(source_info, "path", "")
    base_dir = _safe_getattr(source_info, "base_dir", None)
    return {
        "path": _safe_string(path),
        "source": _safe_getattr(source_info, "source", "filesystem"),
        "scope": _safe_getattr(source_info, "scope", "project"),
        "origin": _safe_getattr(source_info, "origin", "top-level"),
        "baseDir": _safe_string(base_dir) if base_dir is not None else None,
    }


def _project_model_selection_as_model(selection: Any) -> RpcModel | None:
    if selection is None:
        return None
    provider = _safe_getattr(selection, "provider", None)
    endpoint_id = _safe_getattr(selection, "endpoint_id", None)
    model_id = _safe_getattr(selection, "model_id", None)
    if (
        not isinstance(provider, str)
        or not isinstance(endpoint_id, str)
        or not isinstance(model_id, str)
    ):
        provider = _safe_string(provider) if provider is not None else None
        endpoint_id = _safe_string(endpoint_id) if endpoint_id is not None else None
        model_id = _safe_string(model_id) if model_id is not None else None
        if not provider or not endpoint_id or not model_id:
            return None
    return {"provider": provider, "endpointId": endpoint_id, "id": model_id}


def _project_model(session: Any, model: object) -> RpcModel | None:
    provider = _safe_getattr(model, "provider_id", None) or _safe_getattr(
        model, "provider", None
    )
    model_id = _safe_getattr(model, "id", None)
    endpoint_id = _safe_getattr(model, "endpoint_id", None) or _safe_getattr(
        model, "endpoint", None
    )
    if not provider or not endpoint_id or not model_id:
        return None

    name = _safe_getattr(model, "name", None)
    data: RpcModel = {
        "provider": str(provider),
        "endpointId": str(endpoint_id),
        "id": str(model_id),
        "name": name if isinstance(name, str) and name else str(model_id),
    }
    endpoint = _resolve_model_endpoint(session, model)
    if endpoint is not None:
        api = _safe_getattr(endpoint, "api", None)
        if isinstance(api, str) and api:
            data["api"] = api
        base_url = _safe_getattr(endpoint, "base_url", None)
        if isinstance(base_url, str) and base_url:
            data["baseUrl"] = base_url

    modalities = _safe_getattr(model, "input", None)
    if isinstance(modalities, tuple | list):
        data["input"] = [str(modality) for modality in modalities]
    context_window = _safe_getattr(model, "context_window", None)
    if isinstance(context_window, int):
        data["contextWindow"] = context_window
    max_tokens = _safe_getattr(model, "max_tokens", None)
    if isinstance(max_tokens, int):
        data["maxTokens"] = max_tokens
    reasoning = _safe_getattr(model, "reasoning", None)
    if isinstance(reasoning, bool):
        data["reasoning"] = reasoning

    cost = project_model_cost(_safe_getattr(model, "pricing", None))
    if cost is not None:
        data["cost"] = cost
    compat = _project_model_compat(_safe_getattr(model, "compat", None))
    if compat is not None:
        data["compat"] = compat
    return data


def _resolve_model_endpoint(session: Any, model: object) -> object | None:
    provider = _safe_getattr(model, "provider_id", None) or _safe_getattr(
        model, "provider", None
    )
    endpoint_id = _safe_getattr(model, "endpoint_id", None)
    if not provider or not endpoint_id:
        return None
    registry = _safe_getattr(session, "model_registry", None)
    if registry is None:
        return None

    ai_registry = _safe_getattr(registry, "ai_registry", None)
    getter = _safe_getattr(ai_registry, "get_endpoint", None)
    if callable(getter):
        try:
            endpoint = getter(provider, endpoint_id)
        except Exception:
            endpoint = None
        if endpoint is not None:
            return endpoint
    getter = _safe_getattr(registry, "get_endpoint", None)
    if callable(getter):
        try:
            return getter(provider, endpoint_id)
        except Exception:
            return None
    return None


def _project_model_compat(compat: object) -> dict[str, Any] | None:
    if compat is None:
        return None
    to_raw = _safe_getattr(compat, "to_raw", None)
    if callable(to_raw):
        try:
            raw = to_raw()
        except Exception:
            return None
        return raw if isinstance(raw, dict) and raw else None
    return compat if isinstance(compat, dict) and compat else None


def _safe_getattr(target: Any, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not isfinite(value):
        return ""
    if isinstance(value, bool | int | float):
        return str(value)
    return ""


def _snake_to_camel(value: str) -> str:
    if "_" not in value:
        return value
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _is_unknown_model(payload: RpcModel | dict[str, object] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("provider") == "unknown" and payload.get("id") == "unknown"


__all__ = [
    "camelize",
    "project_available_models",
    "project_command_descriptor",
    "project_json_value",
    "project_model_cost",
    "project_model_selection",
    "project_session_listing_item",
    "project_session_state",
    "project_session_stats",
    "project_state_model",
    "session_messages",
]
