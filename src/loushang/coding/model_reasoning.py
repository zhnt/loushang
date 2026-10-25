"""Coding presentation of the active model's reasoning choices."""

from __future__ import annotations

from loushang.ai.model import Model
from loushang.ai.model.reasoning import native_reasoning_effort


def reasoning_choices(session: object) -> tuple[str, ...]:
    getter = getattr(session, "get_available_thinking_levels", None)
    if not callable(getter):
        return ()
    return tuple(level for level in getter() if isinstance(level, str))


def reasoning_description(session: object, level: str) -> str:
    details: list[str] = []
    if level == getattr(session, "thinking_level", None):
        details.append("current")
    model = getattr(session, "model", None)
    if isinstance(model, Model):
        native = native_reasoning_effort(model, level)
        if native is not None and native != level:
            details.append(f"API: {native}")
    return " · ".join(details)


def effective_reasoning_label(session: object) -> str | None:
    level = getattr(session, "thinking_level", None)
    if not isinstance(level, str):
        return None
    model = getattr(session, "model", None)
    if isinstance(model, Model):
        return native_reasoning_effort(model, level) or "off"
    return level


async def select_reasoning_level(session: object, level: str) -> str:
    setter = getattr(session, "set_thinking_level", None)
    if not callable(setter):
        raise RuntimeError("Reasoning selection is not available for this session")
    await setter(level)
    return f"Reasoning: {effective_reasoning_label(session) or level}"


__all__ = [
    "effective_reasoning_label",
    "reasoning_choices",
    "reasoning_description",
    "select_reasoning_level",
]
