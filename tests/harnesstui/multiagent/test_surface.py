from __future__ import annotations

from loushang.harness.multiagent import (
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
)
from loushang.harnesstui.multiagent import (
    AgentTreeSurface,
    build_agent_tree_surface_view,
)
from loushang.tui import RenderConstraints


def _control() -> MultiAgentControl:
    return MultiAgentControl(
        agent_types=AgentTypeRegistry(
            (
                AgentTypeSpec(
                    name="reviewer",
                    maximum_children=2,
                ),
            )
        )
    )


def test_agent_tree_surface_projects_live_facts_and_workspace_references() -> None:
    control = _control()
    renders: list[None] = []
    view = build_agent_tree_surface_view(
        records=control.list_agents(caller=HostCaller()),
        subscribe_facts=control.subscribe_facts,
        request_render=lambda: renders.append(None),
    )
    content = view.content
    assert isinstance(content, AgentTreeSurface)
    content.start()

    child = control.spawn(
        caller=HostCaller(),
        parent_path=control.root_ref.path,
        name="reviewer-1",
        agent_type="reviewer",
    )
    started = control.begin_round(child.ref)
    assert started.record is not None
    control.record_progress(
        child.ref,
        round_id=started.record.round_id,
        recent_activity="Inspecting lifecycle code",
        latest_input_tokens=120,
        output_tokens_delta=35,
        tool_uses_delta=2,
    )
    control.bind_workspace(
        child.ref,
        workspace_ref="git-worktree:/tmp/reviewer-1",
    )

    result = view.render(RenderConstraints(width=100, max_height=30))
    text = "\n".join(line.text for line in result.lines)

    assert view.full_screen_page is True
    assert "reviewer-1" in text
    assert "running · reviewer · round 1" in text
    assert "Inspecting lifecycle code" in text
    assert "120 in · 35 out · 2 tools" in text
    assert "git-worktree:/tmp/reviewer-1" in text
    assert len(renders) == 4

    content.close()
    control.record_progress(
        child.ref,
        round_id=started.record.round_id,
        recent_activity="No longer projected",
    )
    assert len(renders) == 4


def test_agent_tree_surface_preserves_summary_when_later_fact_has_no_progress() -> None:
    control = _control()
    child = control.spawn(
        caller=HostCaller(),
        parent_path=control.root_ref.path,
        name="reviewer",
        agent_type="reviewer",
    )
    started = control.begin_round(child.ref)
    assert started.record is not None
    control.record_progress(
        child.ref,
        round_id=started.record.round_id,
        summary="No blockers",
    )
    records = control.list_agents(caller=HostCaller())
    content = AgentTreeSurface(
        records=records,
        subscribe_facts=control.subscribe_facts,
        request_render=lambda: None,
    )
    content.start()
    control.bind_workspace(child.ref, workspace_ref="workspace-1")

    result = content.render(RenderConstraints(width=80, max_height=20))
    text = "\n".join(line.text for line in result.lines)

    assert "No blockers" in text
    assert "workspace-1" in text
    content.close()
