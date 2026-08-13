from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from loushang.coding.session.builtin_commands import list_builtin_command_descriptors

from loushang.ai.model import ModelSelection
from loushang.coding.ui.completion import coding_inline_completion_provider
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import (
    CODING_CANCELLATION_MESSAGE,
    CODING_INTERRUPTION_MESSAGE,
    build_screen_input_router,
)
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harnesstui.conversation.screen_runner import (
    ConversationInputRouterFactoryPort,
    run_conversation_screen,
)
from loushang.harnesstui.status.provider import StatusProvider


class SmokeSession:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.session_manager = SimpleNamespace(get_cwd=lambda: str(cwd))
        self.current_model = ModelSelection(
            provider="smoke", endpoint_id="local", model_id="fast"
        )
        self.models = [
            self.current_model,
            ModelSelection(provider="smoke", endpoint_id="local", model_id="balanced"),
            ModelSelection(
                provider="openai", endpoint_id="openai-responses", model_id="gpt-5"
            ),
            ModelSelection(
                provider="moonshot",
                endpoint_id="kimi-code-anthropic",
                model_id="kimi-for-coding",
            ),
        ]

    def list_commands(self) -> list[object]:
        return list_builtin_command_descriptors()

    def get_model_selection(self) -> ModelSelection:
        return self.current_model

    def get_available_models(self) -> list[ModelSelection]:
        return list(self.models)

    async def set_model(self, selection: object) -> None:
        if isinstance(selection, ModelSelection):
            self.current_model = selection
            return
        provider = getattr(selection, "provider", None)
        endpoint_id = getattr(selection, "endpoint_id", None)
        model_id = getattr(selection, "model_id", None)
        if (
            isinstance(provider, str)
            and isinstance(endpoint_id, str)
            and isinstance(model_id, str)
        ):
            self.current_model = ModelSelection(
                provider=provider,
                endpoint_id=endpoint_id,
                model_id=model_id,
            )


async def main() -> int:
    cwd = Path.cwd()
    session = SmokeSession(cwd)
    app = ScreenCodingTuiApp(
        model_label="smoke/fast",
        cwd=str(cwd),
        branch="smoke",
        session_label="smoke",
    )
    app.composer.set_completion_provider(
        await coding_inline_completion_provider(session, base_path=cwd)
    )
    status_provider = StatusProvider(
        model_label=app.state.model_label,
        cwd=app.state.cwd,
        branch=app.state.branch,
        session_label=lambda: app.state.session_label,
        thinking_level=lambda: None,
        running=lambda: app.state.running,
    )
    surface_manager = ScreenSurfaceManager(
        app=app,
        session=session,
        status_provider=status_provider,
    )

    async def handle_prompt(text: str) -> int | None:
        app.begin_assistant()
        for chunk in _fake_response_chunks(text):
            app.append_assistant_chunk(chunk)
            await asyncio.sleep(0.04)
        app.end_assistant()
        return None

    return await run_conversation_screen(
        app=app,
        stdin=sys.stdin,
        stdout=sys.stdout,
        handle_prompt=handle_prompt,
        handle_local=surface_manager.handle_text,
        handle_surface_intent=surface_manager.handle_surface_intent,
        on_abort=lambda: None,
        should_exit=lambda text: text in {"/quit", "/exit"},
        is_local_command=surface_manager.is_local_command,
        input_router_factory=cast(
            ConversationInputRouterFactoryPort,
            build_screen_input_router,
        ),
        interruption_message=CODING_INTERRUPTION_MESSAGE,
        cancellation_message=CODING_CANCELLATION_MESSAGE,
    )


def _fake_response_chunks(text: str) -> tuple[str, ...]:
    return (
        "### Native TUI smoke response\n\n",
        f"You submitted: `{text}`\n\n",
        "- Type `/` to inspect slash command completion.\n",
        "- Run `/terminal` to open runtime terminal diagnostics.\n",
        "- Run `/model` to open the model selector overlay.\n",
        "- Type `/quit` to leave the smoke harness.\n",
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
