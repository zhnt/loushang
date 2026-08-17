from __future__ import annotations

from pathlib import Path

from loushang.harnesstui.completion.host import (
    CatalogCompletionProfile,
    PreparedCatalogCompletionHost,
    build_session_catalog_completion_host,
)
from loushang.tui import (
    CombinedCompletionProvider,
    SlashCommandCompletionProvider,
)


async def coding_inline_completion_provider(
    session: object,
    *,
    base_path: Path | None,
) -> SlashCommandCompletionProvider | CombinedCompletionProvider:
    return await coding_completion_host(session).inline_provider(
        base_path=base_path,
    )


def coding_completion_host(session: object) -> PreparedCatalogCompletionHost:
    return build_session_catalog_completion_host(
        session,
        profile=_CODING_COMPLETION_PROFILE,
    )


_CODING_COMPLETION_PROFILE = CatalogCompletionProfile(
    model_command_value="/model",
    model_argument_group="Models",
)
