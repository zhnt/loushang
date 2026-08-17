"""Product-neutral startup facts presented by conversation interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConversationStartupView:
    """Presentation-ready facts for starting a conversation interface."""

    model_label: str | None
    cwd: str
    branch: str | None
    project_label: str
    session_label: str | None
    session_observability_id: str | None


def build_conversation_startup_view(
    *,
    model_label: str | None,
    cwd: str,
    branch: str | None,
    session_label: str | None,
    session_observability_id: str | None,
) -> ConversationStartupView:
    """Compose prepared product facts and a generic cwd display label."""

    return ConversationStartupView(
        model_label=model_label,
        cwd=cwd,
        branch=branch,
        project_label=Path(cwd).name or cwd,
        session_label=session_label,
        session_observability_id=session_observability_id,
    )


__all__ = ["ConversationStartupView", "build_conversation_startup_view"]
