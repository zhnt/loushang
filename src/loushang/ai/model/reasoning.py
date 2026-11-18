"""Unified reasoning levels and their projection onto a model's endpoint."""

from __future__ import annotations

from loushang.ai.model.domain import (
    AnthropicMessagesConfig,
    Model,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
    default_adapter_config,
)
from loushang.foundation.reasoning import (
    REASONING_EFFORTS,
    ReasoningEffort,
    ThinkingLevel,
)


def native_reasoning_effort(model: Model, level: str) -> str | None:
    """Translate a unified strength; Off is a protocol control, not a strength."""
    if level == "off":
        return None
    return getattr(model.adapter, "reasoning_effort_map", {}).get(level, level)


def _supports_effort(model: Model) -> bool:
    match model.adapter or default_adapter_config(model.api or ""):
        case OpenAIResponsesConfig():
            return True
        case OpenAICompletionsConfig(reasoning_effort=True, reasoning_format=mode):
            return mode != "moonshot"
        case AnthropicMessagesConfig(thinking_mode="adaptive"):
            return True
    return False


def _supports_off(model: Model) -> bool:
    capabilities = model.capabilities
    if capabilities.reasoning_required is True:
        return False
    if capabilities.reasoning_required is not False and "none" not in (
        capabilities.reasoning_efforts or ()
    ):
        return False
    match model.adapter or default_adapter_config(model.api or ""):
        case OpenAIResponsesConfig() | AnthropicMessagesConfig():
            return True
        case OpenAICompletionsConfig(reasoning_effort=effort, reasoning_format=mode):
            return effort or mode in {"deepseek", "moonshot", "zai-thinking"}
    return False


def available_thinking_levels(model: Model) -> tuple[ThinkingLevel, ...]:
    """Return distinct choices supported by both the model and its adapter."""
    if not model.capabilities.reasoning:
        return ()
    off: tuple[ThinkingLevel, ...] = ("off",) if _supports_off(model) else ()
    native_values = model.capabilities.reasoning_efforts
    if not native_values or not _supports_effort(model):
        return off
    return (*off, *_distinct_strengths(model, native_values))


def _distinct_strengths(
    model: Model, native_values: tuple[str, ...]
) -> tuple[ReasoningEffort, ...]:
    supported = set(native_values) - {"none"}
    chosen: dict[str, ReasoningEffort] = {}
    for level in REASONING_EFFORTS:
        native = native_reasoning_effort(model, level)
        if native is not None and native in supported:
            if level == native:
                chosen[native] = level
            else:
                chosen.setdefault(native, level)
    return tuple(level for level in REASONING_EFFORTS if level in chosen.values())


def preferred_thinking_level(model: Model) -> ThinkingLevel | None:
    """Project an explicitly configured default when it is a selectable strength."""
    default = model.defaults.get("reasoningEffort")
    if not isinstance(default, str):
        return None
    return next(
        (
            level
            for level in available_thinking_levels(model)
            if native_reasoning_effort(model, level) == default
        ),
        None,
    )


def validate_reasoning_request(
    model: Model,
    *,
    enabled: bool | None,
    effort: str | None,
) -> None:
    """Reject unsupported explicit controls before transport."""
    if enabled is False and model.capabilities.reasoning and not _supports_off(model):
        if model.capabilities.reasoning_required:
            raise ValueError(f"Model {model.id!r} requires reasoning to remain enabled")
        raise ValueError(f"Model {model.id!r} does not support turning reasoning off")
    if effort is None:
        return
    choices = available_thinking_levels(model)
    if effort not in choices:
        available = ", ".join(choices) or "provider default only"
        raise ValueError(
            f"Model {model.id!r} does not support reasoning effort {effort!r}. "
            f"Available levels: {available}"
        )
