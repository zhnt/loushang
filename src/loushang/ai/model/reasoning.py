"""Model reasoning choices and provider-native effort projection."""

from __future__ import annotations

from loushang.ai.model.domain import Model, OpenAICompletionsConfig

_GENERIC_LEVELS = ("minimal", "low", "medium", "high", "xhigh")


def native_reasoning_effort(model: Model, level: str) -> str | None:
    """Translate a generic agent level using the model's adapter contract."""

    if level == "off":
        return None
    mapping = getattr(model.adapter, "reasoning_effort_map", {})
    return mapping.get(level, level)


def available_thinking_levels(model: Model) -> tuple[str, ...]:
    """Return generic levels that have distinct, runnable model-native values."""

    capabilities = model.capabilities
    if not capabilities.reasoning:
        return ("off",)
    result = [] if capabilities.reasoning_required else ["off"]
    native_values = capabilities.reasoning_efforts
    if native_values is None:
        return (*result, *_GENERIC_LEVELS)
    if isinstance(model.adapter, OpenAICompletionsConfig) and not model.adapter.reasoning_effort:
        return tuple(result)

    chosen: dict[str, str] = {}
    for level in _GENERIC_LEVELS:
        native = native_reasoning_effort(model, level)
        if native not in native_values:
            continue
        current = chosen.get(native)
        if current is None or level == native or (level == "xhigh" and native == "max"):
            chosen[native] = level
    result.extend(level for level in _GENERIC_LEVELS if level in chosen.values())
    return tuple(result)


def preferred_thinking_level(model: Model) -> str | None:
    """Choose the model's native default, expressed as a generic agent level."""

    available = available_thinking_levels(model)
    default = model.defaults.get("reasoningEffort")
    if isinstance(default, str):
        for level in available:
            if native_reasoning_effort(model, level) == default:
                return level
    for candidate in ("high", "medium", "low", "xhigh", "minimal"):
        if candidate in available:
            return candidate
    return available[0] if available else None


def validate_reasoning_request(
    model: Model,
    *,
    enabled: bool | None,
    effort: str | None,
) -> None:
    """Reject model-specific effort errors before sending a provider request."""

    capabilities = model.capabilities
    if capabilities.reasoning_required and enabled is False:
        raise ValueError(f"Model {model.id!r} requires reasoning to remain enabled")
    if enabled is not True or effort is None:
        return
    native_values = capabilities.reasoning_efforts
    if native_values is None:
        return
    if isinstance(model.adapter, OpenAICompletionsConfig) and not model.adapter.reasoning_effort:
        return
    native = native_reasoning_effort(model, effort)
    if native not in native_values:
        raise ValueError(
            f"Model {model.id!r} does not support reasoning effort {effort!r}"
        )
