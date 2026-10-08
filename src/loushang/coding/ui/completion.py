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

from ._plugin_completion import with_plugin_management_completion


async def coding_inline_completion_provider(
    session: object,
    *,
    base_path: Path | None,
) -> SlashCommandCompletionProvider | CombinedCompletionProvider:
    return await coding_completion_host(session).inline_provider(
        base_path=base_path,
    )


def coding_completion_host(session: object) -> PreparedCatalogCompletionHost:
    host = build_session_catalog_completion_host(
        session,
        profile=_CODING_COMPLETION_PROFILE,
    )
    return with_plugin_management_completion(host, session=session)


_CODING_COMPLETION_PROFILE = CatalogCompletionProfile(
    model_command_value="/model",
    model_argument_group="Models",
)
