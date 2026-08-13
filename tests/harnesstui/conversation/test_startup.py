from __future__ import annotations

import asyncio

from loushang.ai.model import ModelSelection
from loushang.harnesstui.conversation.agent_application import (
    load_agent_conversation_startup_view,
)
from loushang.harnesstui.conversation.startup import (
    build_conversation_startup_view,
)


def test_build_conversation_startup_view_derives_project_label() -> None:
    view = build_conversation_startup_view(
        model_label="provider/model",
        cwd="/workspace/project",
        branch="main",
        session_label="session",
        session_observability_id="session-id",
    )

    assert view.model_label == "provider/model"
    assert view.cwd == "/workspace/project"
    assert view.branch == "main"
    assert view.project_label == "project"
    assert view.session_label == "session"
    assert view.session_observability_id == "session-id"


def test_build_conversation_startup_view_preserves_root_as_project_label() -> None:
    view = build_conversation_startup_view(
        model_label=None,
        cwd="/",
        branch=None,
        session_label=None,
        session_observability_id=None,
    )

    assert view.project_label == "/"


def test_load_agent_startup_view_prepares_structural_product_session() -> None:
    class Runtime:
        def get_cwd(self) -> str:
            return "/workspace/research"

    class Session:
        session_id = "research-42"
        session_name = "Literature review"

        def __init__(self) -> None:
            self.selection = ModelSelection(
                provider="provider",
                endpoint_id="test-endpoint",
                model_id="initial",
            )

        async def get_model_selection(self) -> ModelSelection:
            return self.selection

    session = Session()

    async def prepare(value: object) -> None:
        assert value is session
        session.selection = ModelSelection(
            provider="provider",
            endpoint_id="test-endpoint",
            model_id="prepared",
        )

    view = asyncio.run(
        load_agent_conversation_startup_view(
            runtime=Runtime(),
            session=session,
            prepare_session=prepare,
        )
    )

    assert view.model_label == "provider:test-endpoint:prepared"
    assert view.cwd == "/workspace/research"
    assert view.project_label == "research"
    assert view.session_label == "Literature review"
    assert view.session_observability_id == "research-42"
