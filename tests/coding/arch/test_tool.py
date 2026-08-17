from __future__ import annotations

import asyncio
from pathlib import Path
from time import monotonic

import pytest

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.coding.arch import (
    CODING_ARCH_TOOL_PACK,
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    ImportGraphToolRuntime,
    create_inspect_import_graph_tool_definition,
    register_coding_arch_tools,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


def _write_package(root: Path) -> Path:
    package = root / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from . import api\n", encoding="utf-8")
    (package / "api.py").write_text("from pkg import core\n", encoding="utf-8")
    (package / "core.py").write_text("from pkg import api\n", encoding="utf-8")
    return package


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _session(
    workspace: Path,
    *,
    mode: CapabilityMountMode,
    allowed_tool_names: list[str] | None = None,
    tool_policy_evaluator: PolicyEvaluator | None = None,
) -> AgentSession:
    manager = asyncio.run(
        SessionManager.new(
            session_dir=workspace / ".sessions",
            cwd=str(workspace),
            persist=False,
        )
    )
    registry = WorkspaceToolRegistry()
    register_coding_arch_tools(registry, mode=mode)
    agent = Agent(
        initial_state={
            "system_prompt": "Coding base prompt",
            "model": _model(),
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )
    return AgentSession(
        agent=agent,
        session_manager=manager,
        tool_registry=registry,
        allowed_tool_names=allowed_tool_names,
        base_prompt="Coding base prompt",
        tool_policy_evaluator=tool_policy_evaluator,
    )


def test_arch_tool_pack_is_separate_and_schema_is_bounded() -> None:
    from loushang.coding.tool_pack import CODING_BUILTIN_TOOL_PACK

    definition = create_inspect_import_graph_tool_definition()

    assert CODING_ARCH_TOOL_PACK.name == "coding.arch.tools"
    assert CODING_ARCH_TOOL_PACK.tools == (INSPECT_IMPORT_GRAPH_TOOL_NAME,)
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in CODING_BUILTIN_TOOL_PACK.tools
    assert definition.execution_mode == "sequential"
    assert "root" in definition.parameters["required"]
    assert definition.parameters["properties"]["query"]["enum"] == [
        "summary",
        "cycles",
        "edges",
        "path",
        "hotspots",
        "boundaries",
    ]
    assert definition.parameters["properties"]["limit"]["maximum"] == 200


def test_arch_mount_modes_and_live_agent_rebinding(tmp_path: Path) -> None:
    _write_package(tmp_path)

    on_demand = _session(tmp_path, mode="on_demand")
    assert on_demand.get_active_tool_names() == []
    assert [tool.name for tool in on_demand.get_all_tools()] == [
        INSPECT_IMPORT_GRAPH_TOOL_NAME
    ]
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in on_demand.agent.system_prompt

    asyncio.run(on_demand.set_active_tools([INSPECT_IMPORT_GRAPH_TOOL_NAME]))
    assert on_demand.get_active_tool_names() == [INSPECT_IMPORT_GRAPH_TOOL_NAME]
    assert [tool.name for tool in on_demand.agent.tools] == [
        INSPECT_IMPORT_GRAPH_TOOL_NAME
    ]
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in on_demand.agent.system_prompt

    always = _session(tmp_path, mode="always")
    assert always.get_active_tool_names() == [INSPECT_IMPORT_GRAPH_TOOL_NAME]
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in always.agent.system_prompt

    disabled = _session(tmp_path, mode="disabled")
    assert disabled.get_all_tools() == []
    assert disabled.get_active_tool_names() == []


def test_arch_always_does_not_bypass_session_allowlist(tmp_path: Path) -> None:
    _write_package(tmp_path)

    session = _session(tmp_path, mode="always", allowed_tool_names=[])

    assert session.get_all_tools() == []
    assert session.get_active_tool_names() == []
    assert session.agent.tools == []


def test_inspect_import_graph_reuses_warm_cache_and_bounds_results(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path)
    runtime = ImportGraphToolRuntime()

    first = runtime.inspect(
        workspace=tmp_path,
        root="pkg",
        package_prefix="pkg",
        imports="all",
        query="edges",
        limit=1,
    )
    started = monotonic()
    second = runtime.inspect(
        workspace=tmp_path,
        root="pkg",
        package_prefix="pkg",
        imports="all",
        query="edges",
        limit=1,
    )
    elapsed = monotonic() - started

    assert first["cache"]["misses"] == 3
    assert second["cache"]["hits"] == 3
    assert len(second["results"]) == 1
    assert second["truncated"] is True
    assert elapsed < 1.0
    assert Path(second["root"]) == package.resolve()

    with pytest.raises(ValueError, match="between 1 and 200"):
        runtime.inspect(workspace=tmp_path, limit=201)


def test_inspect_import_graph_restricts_roots_to_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_package(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.py").write_text("VALUE = 1\n", encoding="utf-8")

    runtime = ImportGraphToolRuntime()

    with pytest.raises(PermissionError, match="within the coding workspace"):
        runtime.inspect(workspace=workspace, root=str(outside))

    symlink = workspace / "escaped"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    with pytest.raises(PermissionError, match="within the coding workspace"):
        runtime.inspect(workspace=workspace, root="escaped")


def test_materialized_arch_tool_runs_through_session_gateway(tmp_path: Path) -> None:
    _write_package(tmp_path)
    session = _session(tmp_path, mode="always")

    result = asyncio.run(
        session.agent.tools[0].execute(
            "arch-call",
            {
                "root": "pkg",
                "package_prefix": "pkg",
                "imports": "all",
                "query": "summary",
                "limit": 10,
            },
        )
    )

    assert result.details["nodes"] == 3
    assert result.details["edges"] == 3
    assert result.details["cache"]["enabled"] is True


def test_arch_tool_honors_session_tool_policy(tmp_path: Path) -> None:
    from loushang.harness.policy_engine import PolicyEngine

    _write_package(tmp_path)
    session = _session(
        tmp_path,
        mode="always",
        tool_policy_evaluator=PolicyEngine(
            blocked_tools=[INSPECT_IMPORT_GRAPH_TOOL_NAME]
        ),
    )

    with pytest.raises(PermissionError, match=INSPECT_IMPORT_GRAPH_TOOL_NAME):
        asyncio.run(
            session.agent.tools[0].execute(
                "blocked-arch-call",
                {"root": "pkg", "package_prefix": "pkg"},
            )
        )
