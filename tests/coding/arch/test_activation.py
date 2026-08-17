from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.arch import INSPECT_IMPORT_GRAPH_TOOL_NAME
from loushang.coding.bootstrap import create_services
from loushang.coding.cli.__main__ import (
    _run_coding_pre_runtime_operation,
    build_builtin_tool_registry,
    default_runtime_builder,
)
from loushang.coding.cli.args import parse_args
from loushang.harness.cli import AgentCliStatePreparationContext
from loushang.harness.config.agent import (
    CapabilityMountMode,
    ControlConfig,
    SettingsManager,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


def _runtime_args(*, no_tools: bool = False) -> SimpleNamespace:
    return SimpleNamespace(no_tools=no_tools, tools=(), no_session=True)


def _create_cli_session(
    tmp_path: Path,
    *,
    mode: CapabilityMountMode,
    no_tools: bool = False,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings = SettingsManager(ControlConfig(capabilities={"coding.arch": mode}))
    services = create_services(settings_manager=settings)
    registry = build_builtin_tool_registry(settings_manager=settings)
    runtime = default_runtime_builder(
        args=_runtime_args(no_tools=no_tools),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=services,
        tool_registry=registry,
    )
    return asyncio.run(runtime.create_session(cwd=str(tmp_path)))


def test_cli_parses_generic_capability_mount_overrides() -> None:
    args = parse_args(
        [
            "--capability",
            "coding.arch=always",
            "--capability",
            "coding.review=disabled",
        ]
    )

    assert args.capability_modes == (
        ("coding.arch", "always"),
        ("coding.review", "disabled"),
    )

    with pytest.raises(SystemExit):
        parse_args(["--capability", "coding.arch=sometimes"])


def test_project_config_decodes_capability_mounts(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "capabilities": {
                    "coding.arch": "always",
                    "coding.review": "on_demand",
                }
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(project_settings_path=settings_path)

    assert manager.get_settings().capabilities == {
        "coding.arch": "always",
        "coding.review": "on_demand",
    }
    assert manager.drain_errors() == []


def test_cli_capability_mount_is_applied_as_session_config_overlay(
    tmp_path: Path,
) -> None:
    manager = SettingsManager(
        ControlConfig(capabilities={"coding.review": "on_demand"})
    )
    services = create_services(settings_manager=manager)
    args = parse_args(["--capability", "coding.arch=always"])
    context = AgentCliStatePreparationContext(
        args=args,
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        services=services,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    result = asyncio.run(
        _run_coding_pre_runtime_operation(context, workflow_runner=None)
    )

    assert result is None
    assert manager.get_settings().capabilities == {
        "coding.review": "on_demand",
        "coding.arch": "always",
    }
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in {
        definition.name
        for definition in build_builtin_tool_registry(
            settings_manager=manager
        ).list_enabled_definitions()
    }


def test_capability_overrides_merge_with_configured_mounts() -> None:
    manager = SettingsManager(ControlConfig(capabilities={"coding.review": "always"}))

    manager.apply_overrides({"capabilities": {"coding.arch": "disabled"}})

    assert manager.get_settings().capabilities == {
        "coding.review": "always",
        "coding.arch": "disabled",
    }


def test_coding_config_controls_default_arch_tool_activation(tmp_path: Path) -> None:
    on_demand = _create_cli_session(tmp_path / "on-demand", mode="on_demand")
    always = _create_cli_session(tmp_path / "always", mode="always")
    disabled = _create_cli_session(tmp_path / "disabled", mode="disabled")

    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in on_demand.get_active_tool_names()
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in {
        definition.name for definition in on_demand.get_all_tools()
    }
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in always.get_active_tool_names()
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in {
        definition.name for definition in disabled.get_all_tools()
    }


def test_no_tools_overrides_always_capability_mount(tmp_path: Path) -> None:
    session = _create_cli_session(tmp_path, mode="always", no_tools=True)

    assert session.get_active_tool_names() == []
    assert session.get_all_tools() == []
    assert session.agent.tools == []


def test_arch_pack_remains_available_without_builtin_tools(tmp_path: Path) -> None:
    settings = SettingsManager(ControlConfig(capabilities={"coding.arch": "always"}))
    services = create_services(settings_manager=settings)
    runtime = default_runtime_builder(
        args=_runtime_args(),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=services,
        tool_registry=WorkspaceToolRegistry(),
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))

    active = set(session.get_active_tool_names())
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in active
    assert not {"bash", "read", "ls", "find", "grep", "write", "edit"}.intersection(
        active
    )
