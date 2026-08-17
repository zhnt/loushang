from __future__ import annotations

import asyncio

from loushang.ai.model import ModelSelection


def test_load_coding_tui_startup_view_resolves_model_and_session_metadata() -> None:
    from loushang.coding.ui.startup import load_coding_tui_startup_view

    class Runtime:
        def get_cwd(self) -> str:
            return "/tmp/project"

    class Session:
        session_id = "sid"
        session_name = "session-name"

        def __init__(self) -> None:
            self.selection = ModelSelection(
                endpoint_id="test-endpoint", provider="unknown", model_id="unknown"
            )

        async def get_model_selection(self) -> ModelSelection:
            return self.selection

        async def get_available_models(self) -> list[ModelSelection]:
            return [
                ModelSelection(
                    endpoint_id="test-endpoint",
                    provider="moonshot",
                    model_id="kimi-for-coding",
                )
            ]

        async def set_model(self, selection: ModelSelection) -> None:
            self.selection = selection

    snapshot = asyncio.run(
        load_coding_tui_startup_view(runtime=Runtime(), session=Session())
    )

    assert snapshot.model_label == "moonshot:test-endpoint:kimi-for-coding"
    assert snapshot.cwd == "/tmp/project"
    assert snapshot.project_label == "project"
    assert snapshot.session_label == "session-name"
    assert snapshot.session_observability_id == "sid"
