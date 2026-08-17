from __future__ import annotations

from loushang.coding.model_selection import (
    ensure_usable_session_model,
)
from loushang.harnesstui.conversation.agent_application import (
    load_agent_conversation_startup_view,
)
from loushang.harnesstui.conversation.startup import (
    ConversationStartupView,
)


async def load_coding_tui_startup_view(
    *, runtime: object, session: object
) -> ConversationStartupView:
    return await load_agent_conversation_startup_view(
        runtime=runtime,
        session=session,
        prepare_session=ensure_usable_session_model,
    )


__all__ = ["load_coding_tui_startup_view"]
