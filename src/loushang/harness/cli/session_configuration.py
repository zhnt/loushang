"""Standard Agent CLI session configuration over injected Product policy."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import TextIO, TypeAlias

from loushang.harness.cli.extension_flags import apply_extension_flag_values

ModelSelectionApplier: TypeAlias = Callable[
    [object, object], object | Awaitable[object]
]
ModelResultWarning: TypeAlias = Callable[[object], str | None]
ModelSelectionResolver: TypeAlias = Callable[[], object | None]


async def configure_agent_cli_session(
    session: object,
    *,
    session_name: str | None,
    extension_flag_values: Mapping[str, bool | str],
    model_selection: object | None,
    thinking_level: object | None,
    apply_model_selection: ModelSelectionApplier | None,
    model_result_warning: ModelResultWarning | None,
    stderr: TextIO,
    resolve_model_selection: ModelSelectionResolver | None = None,
    format_error: Callable[[BaseException], str] = str,
) -> int | None:
    """Apply standard post-resolution CLI values to an Agent session."""

    apply_extension_flag_values(session, extension_flag_values)
    if session_name is not None:
        setter = getattr(session, "set_session_name", None)
        if callable(setter):
            setter(session_name)
    try:
        resolved_model = (
            resolve_model_selection()
            if resolve_model_selection is not None
            else model_selection
        )
        if resolved_model is not None:
            if apply_model_selection is None:
                raise RuntimeError("Model selection is not available.")
            result = await _resolve(apply_model_selection(session, resolved_model))
            warning = (
                model_result_warning(result)
                if model_result_warning is not None
                else None
            )
            if warning:
                stderr.write(f"Warning: {warning}\n")
        if thinking_level is not None:
            setter = getattr(session, "set_thinking_level")
            await _resolve(setter(thinking_level))
    except (RuntimeError, ValueError) as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return 1
    return None


async def _resolve(value: object | Awaitable[object]) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "ModelResultWarning",
    "ModelSelectionApplier",
    "ModelSelectionResolver",
    "configure_agent_cli_session",
]
