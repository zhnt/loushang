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
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in {
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
    asyncio.run(on_demand.dispose())
    asyncio.run(always.dispose())
    asyncio.run(disabled.dispose())


def test_no_tools_overrides_always_capability_mount(tmp_path: Path) -> None:
    session = _create_cli_session(tmp_path, mode="always", no_tools=True)

    assert session.get_active_tool_names() == []
    assert session.get_all_tools() == []
    assert session.agent.tools == []
    asyncio.run(session.dispose())


@pytest.mark.parametrize(
    ("arch_mode", "no_tools"),
    [("disabled", False), ("always", True)],
)
def test_disabled_arch_paths_do_not_resolve_any_capability_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arch_mode: CapabilityMountMode,
    no_tools: bool,
) -> None:
    import loushang.coding.bootstrap as coding_bootstrap

    def reject_plugin_resolution(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("disabled Capability Plugins must not resolve")

    monkeypatch.setattr(
        coding_bootstrap,
        "prepare_coding_capability_plugin_composition",
        reject_plugin_resolution,
    )
    settings = SettingsManager(
        ControlConfig(
            capabilities={
                "coding.arch": arch_mode,
                "coding.lsp": "disabled" if not no_tools else "always",
            }
        )
    )
    runtime = default_runtime_builder(
        args=_runtime_args(no_tools=no_tools),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=create_services(settings_manager=settings),
        tool_registry=build_builtin_tool_registry(settings_manager=settings),
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))

    assert session._coding_capability_plugin_assembly is None
    asyncio.run(session.dispose())


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
    asyncio.run(session.dispose())


def test_production_allowlist_filters_arch_tool_without_bypassing_provider(
    tmp_path: Path,
) -> None:
    settings = SettingsManager(
        ControlConfig(capabilities={"coding.arch": "always"})
    )
    args = _runtime_args()
    args.tools = ("read",)
    runtime = default_runtime_builder(
        args=args,
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=create_services(settings_manager=settings),
        tool_registry=build_builtin_tool_registry(settings_manager=settings),
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))
    assembly = session._coding_capability_plugin_assembly

    assert assembly is not None
    assert "coding.arch" in {
        item.capability_id
        for item in assembly.plugin_assembly.resolved_providers.entries
    }
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in {
        definition.name for definition in session.get_all_tools()
    }
    asyncio.run(session.dispose())


def test_arch_and_lsp_share_one_product_composition_and_session_graph(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from . import child\n", encoding="utf-8")
    (package / "child.py").write_text("VALUE = 1\n", encoding="utf-8")
    session = _create_cli_session(tmp_path, mode="always")
    assembly = session._coding_capability_plugin_assembly

    assert assembly is not None
    assert session._coding_lsp_plugin_assembly is assembly
    assert {
        item.capability_id for item in assembly.plugin_assembly.resolved_providers.entries
    } == {"coding.arch", "coding.lsp"}
    arch_provider = next(
        item.provider
        for item in assembly.plugin_assembly.resolved_providers.entries
        if item.capability_id == "coding.arch"
    )
    assert tuple(
        (requirement.capability, requirement.facets, requirement.optional)
        for requirement in arch_provider.requirements
    ) == (
        ("harness.workspace", ("list", "read", "search"), False),
    )
    assert {
        item.candidate.contribution.collection_id
        for item in assembly.plugin_assembly.product_composition.catalog_admissions
        if item.plugin_id in {"coding.arch.default", "coding.lsp.default"}
    } == {"coding.arch.tools", "coding.lsp.tools"}
    assert (
        assembly.session_inputs.product_composition
        is assembly.plugin_assembly.product_composition
    )
    assert len(assembly.session_inputs.component_requests) == 2
    assert assembly.tool_owner_for("coding.arch.default") is not None
    assert assembly.tool_owner_for("coding.lsp.default") is not None

    arch_tool = next(
        tool
        for tool in session.agent.tools
        if tool.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
    )
    result = asyncio.run(
        arch_tool.execute(
            "arch-production-call",
            {
                "root": "pkg",
                "package_prefix": "pkg",
                "query": "summary",
            },
        )
    )
    arch_config = next(
        item.configuration
        for item in assembly.selection.plan.effective_configuration_set.entries
        if item.plugin_id == "coding.arch.default"
        and item.contribution_id == "coding-arch-default"
    )
    private_root = Path(str(arch_config["privateDataRoot"]))
    assert result.details["nodes"] == 2
    assert (private_root / "import-facts-v1.json").is_file()
    assert assembly._private_state_cleaned is False

    asyncio.run(session.dispose())

    assert assembly._private_state_cleaned is True
    assert private_root.exists() is False


def test_arch_provider_and_tool_work_when_lsp_is_disabled(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("import os\n", encoding="utf-8")
    settings = SettingsManager(
        ControlConfig(
            capabilities={"coding.arch": "always", "coding.lsp": "disabled"}
        )
    )
    services = create_services(settings_manager=settings)
    runtime = default_runtime_builder(
        args=_runtime_args(),
        cwd=tmp_path,
        session_dir=tmp_path / "sessions",
        services=services,
        tool_registry=build_builtin_tool_registry(settings_manager=settings),
    )

    session = asyncio.run(runtime.create_session(cwd=str(tmp_path)))
    assembly = session._coding_capability_plugin_assembly

    assert assembly is not None
    assert session._coding_lsp_plugin_assembly is None
    assert tuple(
        item.capability_id for item in assembly.plugin_assembly.resolved_providers.entries
    ) == ("coding.arch",)
    assert assembly.tool_owner_for("coding.lsp.default") is None
    assert assembly.tool_owner_for("coding.arch.default") is not None
    assert INSPECT_IMPORT_GRAPH_TOOL_NAME in session.get_active_tool_names()
    assert {"document_outline", "inspect_symbol"}.isdisjoint(
        tool.name for tool in session.get_all_tools()
    )

    asyncio.run(session.dispose())
