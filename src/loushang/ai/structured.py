from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, cast

from loushang.ai.errors import AIRequestValidationError
from loushang.ai.types import AssistantMessage, TextPart
from loushang.foundation.json import JSONValue, require_json_mapping

StructuredOutputMode = Literal["json_object", "json_schema"]

if TYPE_CHECKING:
    from loushang.ai.options import CallOptions


@dataclass(frozen=True, slots=True)
class StructuredOutputOptions:
    mode: StructuredOutputMode
    schema: Mapping[str, JSONValue] | type | None = None
    strict: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"json_object", "json_schema"}:
            raise ValueError(f"Unsupported structured output mode: {self.mode!r}")
        if self.mode == "json_schema" and self.schema is None:
            raise ValueError("json_schema structured output requires schema")


@dataclass(frozen=True, slots=True)
class StructuredOutputResult:
    raw: AssistantMessage
    parsed: object


class StructuredOutputError(AIRequestValidationError):
    default_source = "loushang.ai.structured"


def get_structured_output_options(
    options: object | None,
) -> StructuredOutputOptions | None:
    if options is None:
        return None
    output = getattr(options, "output", None)
    return output if isinstance(output, StructuredOutputOptions) else None


def with_structured_output_options(
    options: object | None,
    output: StructuredOutputOptions,
) -> "CallOptions":
    from loushang.ai.options import CallOptions

    if options is None:
        return CallOptions(output=output)
    return replace(cast(Any, options), output=output)


def openai_chat_response_format(options: object | None) -> dict[str, object] | None:
    output = get_structured_output_options(options)
    if output is None:
        return None
    if output.mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _schema_name(output.schema),
            "schema": _schema_mapping(output.schema),
            "strict": output.strict,
        },
    }


def openai_responses_text_format(options: object | None) -> dict[str, object] | None:
    output = get_structured_output_options(options)
    if output is None:
        return None
    if output.mode == "json_object":
        return {"format": {"type": "json_object"}}
    return {
        "format": {
            "type": "json_schema",
            "name": _schema_name(output.schema),
            "schema": _schema_mapping(output.schema),
            "strict": output.strict,
        }
    }


def parse_structured_output(
    message: AssistantMessage,
    output: StructuredOutputOptions,
) -> StructuredOutputResult:
    raw_text = _assistant_text(message)
    try:
        parsed_json = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise StructuredOutputError(
            "Structured output was not valid JSON",
            details={"position": error.pos, "reason": error.msg},
        ) from error

    if output.mode == "json_object" and not isinstance(parsed_json, dict):
        raise StructuredOutputError(
            "Structured output JSON mode requires an object",
            details={"kind": type(parsed_json).__name__},
        )

    parsed = _parse_schema_type(parsed_json, output.schema)
    return StructuredOutputResult(raw=message, parsed=parsed)


def _assistant_text(message: AssistantMessage) -> str:
    text = "".join(part.text for part in message.content if isinstance(part, TextPart))
    if not text:
        raise StructuredOutputError("Structured output response did not contain text")
    return text


def _parse_schema_type(
    value: object, schema: Mapping[str, JSONValue] | type | None
) -> object:
    if not isinstance(schema, type):
        return value
    model_validate = getattr(schema, "model_validate", None)
    if callable(model_validate):
        try:
            return model_validate(value)
        except Exception as error:
            raise StructuredOutputError(
                "Structured output failed schema validation",
                details={"schema": schema.__name__},
            ) from error
    parse_obj = getattr(schema, "parse_obj", None)
    if callable(parse_obj):
        try:
            return parse_obj(value)
        except Exception as error:
            raise StructuredOutputError(
                "Structured output failed schema validation",
                details={"schema": schema.__name__},
            ) from error
    raise StructuredOutputError(
        "Structured output schema type must expose model_validate or parse_obj",
        details={"schema": schema.__name__},
    )


def _schema_mapping(
    schema: Mapping[str, JSONValue] | type | None,
) -> dict[str, JSONValue]:
    if isinstance(schema, Mapping):
        return require_json_mapping(schema, name="schema")
    if isinstance(schema, type):
        model_json_schema = getattr(schema, "model_json_schema", None)
        if callable(model_json_schema):
            raw = model_json_schema()
            if isinstance(raw, Mapping):
                return require_json_mapping(raw, name="schema")
        schema_json = getattr(schema, "schema", None)
        if callable(schema_json):
            raw = schema_json()
            if isinstance(raw, Mapping):
                return require_json_mapping(raw, name="schema")
    raise StructuredOutputError("json_schema structured output requires a JSON schema")


def _schema_name(schema: Mapping[str, JSONValue] | type | None) -> str:
    if isinstance(schema, type):
        return _sanitize_schema_name(schema.__name__)
    if isinstance(schema, Mapping):
        title = schema.get("title")
        if isinstance(title, str) and title:
            return _sanitize_schema_name(title)
    return "structured_output"


def _sanitize_schema_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return normalized or "structured_output"
