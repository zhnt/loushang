from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources.watcher import ResourceChangeWatcher


def test_resource_change_watcher_establishes_baseline_then_reports_changes(
    tmp_path,
) -> None:
    watched = tmp_path / "prompts"
    watched.mkdir()
    prompt = watched / "review.md"
    prompt.write_text("first", encoding="utf-8")
    calls: list[str] = []
    watcher = ResourceChangeWatcher(
        get_paths=lambda: [watched],
        on_change=lambda: calls.append("reload"),
    )

    assert asyncio.run(watcher.poll_once()) is False

    prompt.write_text("second", encoding="utf-8")

    assert asyncio.run(watcher.poll_once()) is True
    assert asyncio.run(watcher.poll_once()) is False
    assert calls == ["reload"]


def test_agent_session_resource_watch_poll_uses_resource_refresh_pipeline(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    prompts = project / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "review.md").write_text("Initial prompt.", encoding="utf-8")

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project)
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base"}),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "sessions", cwd=str(project), persist=False
            )
        ),
        resource_loader=loader,
        resource_bundle=bundle,
        base_prompt="Base",
    )

    assert asyncio.run(session.poll_resource_changes()) is False

    (prompts / "plan.md").write_text("Plan prompt.", encoding="utf-8")

    assert asyncio.run(session.poll_resource_changes()) is True
    assert "Plan prompt." in session.agent.system_prompt


def test_agent_session_dispose_stops_resource_watcher(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base"}),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "sessions", cwd=str(project), persist=False
            )
        ),
        resource_loader=DefaultResourceLoader(),
        base_prompt="Base",
    )

    async def scenario() -> None:
        session.start_resource_watcher(interval_seconds=60)
        assert session._composition.resource_watch_controller.is_running is True
        await session.dispose()

    asyncio.run(scenario())

    assert session._composition.resource_watch_controller.is_running is False
