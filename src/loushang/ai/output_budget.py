from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loushang.ai.options import get_max_output_tokens

DEFAULT_MAX_OUTPUT_TOKEN_CAP = 32_000
DEFAULT_MAX_OUTPUT_TOKEN_FALLBACK = 8_192


@dataclass(frozen=True)
class OutputTokenBudget:
    value: int
    source: str
    explicit: bool


def default_output_tokens_from_capability(max_tokens: object) -> int:
    value = _positive_int(max_tokens)
    if value is None:
        return DEFAULT_MAX_OUTPUT_TOKEN_FALLBACK
    return min(value, DEFAULT_MAX_OUTPUT_TOKEN_CAP)


def resolve_output_token_budget(
    model: Any,
    resolved_request: Any,
    options: Any = None,
) -> OutputTokenBudget:
    default_value = _positive_int(getattr(resolved_request, "max_output_tokens", None))
    if default_value is not None:
        return OutputTokenBudget(default_value, "request", True)

    override_raw = get_max_output_tokens(options)
    if isinstance(override_raw, int):
        return OutputTokenBudget(override_raw, "options", True)

    capabilities = getattr(resolved_request, "capabilities", None)
    capability_max = _positive_int(getattr(capabilities, "max_tokens", None))
    if capability_max is not None:
        return OutputTokenBudget(
            min(capability_max, DEFAULT_MAX_OUTPUT_TOKEN_CAP),
            "capabilities",
            False,
        )

    model_max = _positive_int(getattr(model, "max_tokens", None))
    if model_max is not None:
        return OutputTokenBudget(
            min(model_max, DEFAULT_MAX_OUTPUT_TOKEN_CAP),
            "model",
            False,
        )

    return OutputTokenBudget(DEFAULT_MAX_OUTPUT_TOKEN_FALLBACK, "fallback", False)


def _positive_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )
