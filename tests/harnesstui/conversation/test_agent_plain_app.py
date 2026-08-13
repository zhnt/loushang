from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace
from typing import Any, cast

from loushang.ai.model import ModelSelection
from loushang.harness.commands import CommandDescriptor
from loushang.harnesstui.conversation.agent_plain_app import (
    build_agent_plain_conversation_ports,
)


def test_agent_plain_ports_bind_structural_research_session() -> None:
    settings = object()

    class ResearchSession:
        settings_manager = settings

        def get_model_selection(self) -> ModelSelection:
            return ModelSelection(
                endpoint_id="test-endpoint", provider="research", model_id="analyst"
            )

        def get_available_models(self) -> tuple[ModelSelection, ...]:
            return (
                ModelSelection(
                    endpoint_id="test-endpoint", provider="research", model_id="analyst"
                ),
                ModelSelection(
                    endpoint_id="test-endpoint",
                    provider="research",
                    model_id="reviewer",
                ),
            )

        def list_commands(self) -> tuple[CommandDescriptor[object], ...]:
            return (
                CommandDescriptor(
                    name="report",
                    description="Build a research report",
                    source="research",
                ),
            )

    async def select_model(query: str, _chooser: object | None) -> str:
        return f"selected:{query}"

    ports = build_agent_plain_conversation_ports(
        session=ResearchSession(),
        renderer=cast(Any, object()),
        event_renderer=cast(Any, SimpleNamespace(last_error_message=None)),
        stderr=StringIO(),
        verbose=False,
        emit=lambda _label, _data=None: None,
        trace=lambda _name, **_data: None,
        now=lambda: 1.0,
        controller=cast(Any, object()),
        get_operations=cast(Any, lambda: object()),
        select_model=select_model,  # type: ignore[arg-type]
        hotkeys=lambda: "research hotkeys",
        debug_status=lambda _path, _scopes: "research debug",
        enable_debug=lambda **_kwargs: None,  # type: ignore[arg-type]
        disable_debug=lambda: None,
        suppress_cancelled_error=lambda _message: False,
    )

    commands = asyncio.run(ports.snapshot_commands())

    assert [command.name for command in commands if command.source == "research"] == [
        "report"
    ]
    assert "research:test-endpoint:analyst" in asyncio.run(ports.format_models(""))
    assert asyncio.run(ports.select_model("reviewer", None)) == "selected:reviewer"
    assert ports.settings_manager is settings
    assert ports.command_effect("models", cast(Any, object())) is not None
