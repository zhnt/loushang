"""Single internal codec for normalized Coding LSP server definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loushang.coding.lsp.model import LspServerDefinition

LSP_SERVER_DEFINITION_FIELDS = frozenset(
    {
        "command",
        "environment",
        "id",
        "initialization_options",
        "language_extensions",
        "priority",
        "request_timeout_seconds",
        "root_markers",
        "settings",
        "shutdown_timeout_seconds",
        "source",
        "startup_timeout_seconds",
    }
)


def decode_lsp_server_definition(
    value: object,
    *,
    source: str | None = None,
    require_exact_fields: bool = False,
) -> LspServerDefinition:
    """Decode user-config or canonical Provider JSON through one rule set."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError("server declarations must be objects")
    expected = (
        LSP_SERVER_DEFINITION_FIELDS
        if source is None
        else LSP_SERVER_DEFINITION_FIELDS - {"source"}
    )
    actual = frozenset(value)
    if require_exact_fields:
        if actual != expected:
            raise ValueError("server definition fields do not match the exact contract")
    else:
        unknown = actual - expected
        if unknown:
            raise ValueError(f"unknown server fields: {', '.join(sorted(unknown))}")

    raw_id = value.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise TypeError("server id must be a non-empty string")
    command = _string_sequence(value.get("command"), name="server command")
    language_extensions = value.get("language_extensions")
    if not isinstance(language_extensions, Mapping) or any(
        not isinstance(language, str) or not language
        for language in language_extensions
    ):
        raise TypeError("server language_extensions must be an object")
    normalized_languages = {
        language: _string_sequence(
            extensions,
            name="language_extensions",
        )
        for language, extensions in language_extensions.items()
    }
    resolved_source = source if source is not None else value.get("source")
    if not isinstance(resolved_source, str) or not resolved_source.strip():
        raise TypeError("server source must be a non-empty string")

    return LspServerDefinition(
        id=raw_id.strip(),
        command=command,
        language_extensions=normalized_languages,
        root_markers=_string_sequence(
            value.get("root_markers", ()),
            name="server root_markers",
        ),
        priority=_integer_field(value, "priority", 0),
        environment=_string_mapping(value.get("environment", {}), "environment"),
        initialization_options=_object_mapping(
            value.get("initialization_options", {}),
            "initialization_options",
        ),
        settings=_object_mapping(value.get("settings", {}), "settings"),
        startup_timeout_seconds=_number_field(
            value,
            "startup_timeout_seconds",
            20.0,
        ),
        request_timeout_seconds=_number_field(
            value,
            "request_timeout_seconds",
            15.0,
        ),
        shutdown_timeout_seconds=_number_field(
            value,
            "shutdown_timeout_seconds",
            3.0,
        ),
        source=resolved_source.strip(),
    )


def encode_lsp_server_definition(
    value: LspServerDefinition,
) -> dict[str, object]:
    """Encode the exact canonical Provider/replay representation."""

    if not isinstance(value, LspServerDefinition):
        raise TypeError("LSP server definition codec requires a definition")
    return {
        "command": list(value.command),
        "environment": dict(value.environment),
        "id": value.id,
        "initialization_options": _thaw_json(value.initialization_options),
        "language_extensions": {
            language: list(extensions)
            for language, extensions in value.language_extensions.items()
        },
        "priority": value.priority,
        "request_timeout_seconds": value.request_timeout_seconds,
        "root_markers": list(value.root_markers),
        "settings": _thaw_json(value.settings),
        "shutdown_timeout_seconds": value.shutdown_timeout_seconds,
        "source": value.source,
        "startup_timeout_seconds": value.startup_timeout_seconds,
    }


def _string_sequence(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or any(
        not isinstance(item, str) for item in value
    ):
        raise TypeError(f"{name} must be a string array")
    return tuple(cast(Sequence[str], value))


def _integer_field(value: Mapping[object, object], name: str, default: int) -> int:
    item = value.get(name, default)
    if not isinstance(item, int) or isinstance(item, bool):
        raise TypeError(f"server {name} must be an integer")
    return item


def _number_field(value: Mapping[object, object], name: str, default: float) -> float:
    item = value.get(name, default)
    if not isinstance(item, int | float) or isinstance(item, bool):
        raise TypeError(f"server {name} must be a number")
    return float(item)


def _string_mapping(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError(f"server {name} must map strings to strings")
    return dict(value)


def _object_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"server {name} must be an object")
    return dict(value)


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(name): _thaw_json(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


__all__ = [
    "LSP_SERVER_DEFINITION_FIELDS",
    "decode_lsp_server_definition",
    "encode_lsp_server_definition",
]
