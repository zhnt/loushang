"""Coding model-policy adapter over AI values and Harness session operations."""

from __future__ import annotations

from collections.abc import Iterable

from loushang.ai.model import ModelSelection
from loushang.harness.session.model_preferences import (
    PreferredModel,
    persistence_warning_message,
    preferred_model_candidates,
)
from loushang.harness.session.model_selection import (
    ModelSelectionApplyResult,
    apply_session_model_selection,
)
from loushang.harness.session.model_selection import (
    ensure_usable_session_model as _ensure_usable_session_model,
)

PREFERRED_CODING_MODELS = (
    PreferredModel("kimi-code", "kimi-code-anthropic", "kimi-for-coding"),
)


async def apply_model_selection(
    session: object,
    selection: object,
    *,
    settings_manager: object | None = None,
    scope: str = "global",
) -> ModelSelectionApplyResult:
    resolved_settings_manager = (
        settings_manager
        if settings_manager is not None
        else getattr(session, "settings_manager", None)
    )
    persist = getattr(resolved_settings_manager, "set_default_model", None)
    if not callable(persist):
        return await apply_session_model_selection(session, selection)

    def persist_default(model: ModelSelection) -> object:
        return persist(model, scope=scope)

    return await apply_session_model_selection(
        session,
        selection,
        persist=persist_default,
    )


async def ensure_usable_session_model(session: object) -> ModelSelection | None:
    return await _ensure_usable_session_model(session, candidates=_model_candidates)


async def _model_candidates(session: object) -> Iterable[object]:
    return await preferred_model_candidates(session, PREFERRED_CODING_MODELS)


__all__ = [
    "ModelSelectionApplyResult",
    "PREFERRED_CODING_MODELS",
    "PreferredModel",
    "apply_model_selection",
    "ensure_usable_session_model",
    "persistence_warning_message",
]
