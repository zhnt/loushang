from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.harnesstui.conversation.agent_surfaces import (
    build_standard_agent_screen_surface_workflow_ports,
)


class _Session:
    session_id = "research-session"
    session_name: str | None = "Research"
    settings_manager = None

    def get_user_messages_for_forking(self) -> tuple[dict[str, str], ...]:
        return ({"entry_id": "entry-1", "text": "Investigate this."},)

    async def set_session_name(self, name: str | None) -> None:
        self.session_name = name

    async def ask_side_question(self, question: str) -> str:
        return f"Answer: {question}"

    def cancel_side_question(self) -> None:
        return None


class _Runtime:
    async def fork_session_operation(
        self,
        target: str,
        *,
        position: str,
    ) -> SimpleNamespace:
        assert target == "entry-1"
        assert position == "before"
        return SimpleNamespace(cancelled=False, payload="Investigate this.")


def test_standard_agent_surfaces_bind_structural_product_session_operations() -> None:
    session = _Session()
    labels: list[str | None] = []
    renders: list[str] = []

    async def select_model(value: str) -> str:
        return value

    async def build_settings_content() -> object:
        return {"product": "research"}

    ports = build_standard_agent_screen_surface_workflow_ports(
        session,
        runtime=_Runtime(),
        select_model=select_model,
        set_model_label=lambda _label: None,
        set_session_label=labels.append,
        build_settings_content=build_settings_content,
        terminal_diagnostics=lambda: "research terminal",
        hotkeys=lambda: "research hotkeys",
        request_render=renders.append,
    )

    assert ports.build_resume_surface is None
    assert ports.activate_continuity is None
    assert ports.build_delete_surface is None
    assert ports.delete_continuity is None
    assert ports.build_fork_surface is not None
    assert ports.fork_session is not None
    assert ports.build_rename_surface is not None
    assert ports.rename_session is not None
    assert ports.build_side_question_surface is not None

    fork_surface = ports.build_fork_surface()
    assert fork_surface.purpose == "fork"
    result = asyncio.run(ports.fork_session("entry-1"))
    assert result.status == "Forked from selected prompt"
    assert result.composer_text == "Investigate this."

    assert asyncio.run(ports.rename_session("New research")) == (
        "Session renamed to New research"
    )
    assert session.session_name == "New research"
    assert labels == ["New research"]

    side_question = ports.build_side_question_surface("What changed?")
    assert side_question.purpose == "dialog"
