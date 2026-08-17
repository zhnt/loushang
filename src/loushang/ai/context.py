from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import copy
from dataclasses import dataclass
from typing import Any

from loushang.ai.diagnostics import NormalizationDiagnostic
from loushang.ai.messages import normalize_messages_result
from loushang.ai.options import PairingMode
from loushang.ai.types import (
    AssistantMessage,
    Context,
    Message,
    Tool,
    ToolResultMessage,
    UserMessage,
)

_CONTEXT_KEYS = frozenset({"system_prompt", "systemPrompt", "messages", "tools"})


@dataclass(frozen=True, slots=True)
class NormalizedContext:
    system_prompt: str | None
    messages: tuple[Message, ...] = ()
    tools: tuple[Tool, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "messages": self.messages,
            "tools": self.tools,
        }


@dataclass(frozen=True)
class NormalizationResult:
    context: NormalizedContext
    diagnostics: tuple[NormalizationDiagnostic, ...] = ()


def normalize_context(
    context: Context | Mapping[str, Any] | NormalizedContext | None,
    *,
    model=None,
    pairing_mode: PairingMode = "strict",
) -> NormalizedContext:
    return normalize_context_result(
        context,
        model=model,
        pairing_mode=pairing_mode,
    ).context


def normalize_context_result(
    context: Context | Mapping[str, Any] | NormalizedContext | None,
    *,
    model=None,
    pairing_mode: PairingMode = "strict",
) -> NormalizationResult:
    if isinstance(context, NormalizedContext):
        tools = _normalize_tools(context.tools)
        message_result = normalize_messages_result(
            list(context.messages),
            tools=list(tools),
            model=model,
            pairing_mode=pairing_mode,
        )
        return NormalizationResult(
            context=NormalizedContext(
                system_prompt=_optional_system_prompt(
                    context.system_prompt,
                    "system_prompt",
                ),
                messages=tuple(_validate_normalized_messages(message_result.messages)),
                tools=tools,
            ),
            diagnostics=message_result.diagnostics,
        )

    if context is None:
        return NormalizationResult(context=NormalizedContext(system_prompt=None))

    if isinstance(context, Context):
        tools = _normalize_tools(context.tools)
        message_result = normalize_messages_result(
            list(context.messages),
            tools=None if tools is None else list(tools),
            model=model,
            pairing_mode=pairing_mode,
        )
        return NormalizationResult(
            context=NormalizedContext(
                system_prompt=_optional_system_prompt(
                    context.system_prompt,
                    "system_prompt",
                ),
                messages=tuple(_validate_normalized_messages(message_result.messages)),
                tools=tools,
            ),
            diagnostics=message_result.diagnostics,
        )

    if not isinstance(context, Mapping):
        raise TypeError(f"Unsupported context type: {type(context)!r}")
    _reject_unknown_context_fields(context)
    messages = list(context.get("messages", ()))
    system_prompt = _coalesce_system_prompt(
        _optional_system_prompt(context.get("system_prompt"), "system_prompt"),
        _optional_system_prompt(context.get("systemPrompt"), "systemPrompt"),
        _extract_system_prompt(messages),
    )
    tools = _normalize_tools(context.get("tools"))
    stripped_messages, message_paths = _strip_system_messages_with_paths(messages)
    message_result = normalize_messages_result(
        stripped_messages,
        tools=None if tools is None else list(tools),
        model=model,
        pairing_mode=pairing_mode,
        message_paths=message_paths,
    )
    normalized_messages = _validate_normalized_messages(message_result.messages)
    return NormalizationResult(
        context=NormalizedContext(
            system_prompt=system_prompt,
            messages=tuple(normalized_messages),
            tools=tools,
        ),
        diagnostics=message_result.diagnostics,
    )


def ensure_normalized_context(
    context: Context | Mapping[str, Any] | NormalizedContext | None,
    *,
    model=None,
    pairing_mode: PairingMode = "strict",
) -> NormalizedContext:
    return normalize_context(context, model=model, pairing_mode=pairing_mode)


def is_normalized_context(context: object) -> bool:
    return isinstance(context, NormalizedContext)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _reject_unknown_context_fields(context: Mapping[str, Any]) -> None:
    unknown = sorted(str(key) for key in context if key not in _CONTEXT_KEYS)
    if unknown:
        fields = ", ".join(repr(key) for key in unknown)
        raise TypeError(f"Unsupported Context field(s): {fields}")


def _optional_system_prompt(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported {field_name} type: {type(value)!r}")


def _coalesce_system_prompt(*parts: str | None) -> str | None:
    resolved = [part for part in parts if part]
    if not resolved:
        return None
    return "\n".join(resolved)


def _extract_system_prompt(messages: Iterable[object]) -> str | None:
    parts: list[str] = []
    for message in messages:
        if isinstance(message, Mapping) and message.get("role") in {
            "system",
            "developer",
        }:
            content = message.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
    if not parts:
        return None
    return "\n".join(parts)


def _strip_system_messages(messages: Iterable[object]) -> list[object]:
    stripped, _paths = _strip_system_messages_with_paths(messages)
    return stripped


def _strip_system_messages_with_paths(
    messages: Iterable[object],
) -> tuple[list[object], list[str]]:
    normalized: list[object] = []
    paths: list[str] = []
    for index, message in enumerate(messages):
        if isinstance(message, Mapping) and message.get("role") in {
            "system",
            "developer",
        }:
            continue
        normalized.append(message)
        paths.append(f"messages[{index}]")
    return normalized, paths


def _validate_normalized_messages(messages: list[object]) -> list[Message]:
    normalized: list[Message] = []
    for message in messages:
        if isinstance(message, (AssistantMessage, ToolResultMessage, UserMessage)):
            normalized.append(message)
            continue
        raise TypeError(
            f"Unsupported message type after normalization: {type(message)!r}"
        )
    return normalized


def _normalize_tools(tools: Any) -> tuple[Tool, ...]:
    if tools is None:
        return ()
    normalized: list[Tool] = []
    for tool in tools:
        if isinstance(tool, Tool):
            if not isinstance(tool.description, str):
                raise TypeError("Unsupported tool description type")
            normalized.append(
                Tool(
                    name=_normalize_tool_name(tool.name),
                    description=tool.description,
                    parameters=_normalize_tool_parameters(tool.parameters),
                )
            )
            continue
        if isinstance(tool, dict):
            description = tool.get("description", "")
            if not isinstance(description, str):
                raise TypeError("Unsupported tool description type")
            normalized.append(
                Tool(
                    name=_normalize_tool_name(tool.get("name")),
                    description=description,
                    parameters=_normalize_tool_parameters(
                        tool.get("parameters", {"type": "object"})
                    ),
                )
            )
            continue
        raise TypeError(f"Unsupported tool type: {type(tool)!r}")
    return tuple(normalized)


def _normalize_tool_name(name: object) -> str:
    if isinstance(name, str) and name:
        return name
    raise TypeError(f"Unsupported tool name type: {type(name)!r}")


def _normalize_tool_parameters(parameters: object) -> dict[str, Any]:
    if isinstance(parameters, dict):
        return copy(parameters)
    raise TypeError(f"Unsupported tool parameters type: {type(parameters)!r}")
